import logging
import os
import shutil
import shlex
from subprocess import check_call
from typing import Union, List

from ozy import OzyError
from ozy.config import resolve, load_config
from ozy.files import get_ozy_cache_dir
from ozy.installers import SUPPORTED_INSTALLERS

_LOGGER = logging.getLogger(__name__)


def ensure_keys(name, config, *keys):
    values = []
    for required_key in keys:
        if required_key not in config:
            raise OzyError(f"Missing required key '{required_key}' in '{name}'")
        values.append(config[required_key])
    return values


def _fixup_one_command(command):
    if isinstance(command, list):
        return command
    return shlex.split(command)


def fixup_post_install(post_install: Union[list, str]) -> List[List[str]]:
    if not post_install:
        return []
    if isinstance(post_install, str):
        return [_fixup_one_command(post_install)]
    post_install = [_fixup_one_command(x) for x in post_install]
    return post_install


class App:
    def __init__(self, name, root_config):
        self._name = name
        self._root_config = root_config
        self._config = resolve(root_config['apps'][name], self._root_config.get('templates', {}))
        self._executable_path = self._config.get('executable_path', self.name)
        self._relocatable = self._config.get('relocatable', True)
        self._post_install = fixup_post_install(self._config.get('post_install', []))
        self._version, install_type = ensure_keys(name, self._config, 'version', 'type')
        if install_type not in SUPPORTED_INSTALLERS:
            raise OzyError(f"Unsupported installation type '{install_type}'")
        self._installer = SUPPORTED_INSTALLERS[install_type](name, self._config)

    def __str__(self):
        return f'{self.name} {self._version} ({self._installer})'

    @property
    def name(self) -> str:
        return self._name

    @property
    def config(self) -> dict:
        return self._config

    @property
    def version(self) -> str:
        return self._version

    @property
    def install_path(self) -> str:
        return os.path.join(get_ozy_cache_dir(), self.name, self.version)

    @property
    def executable(self) -> str:
        return os.path.join(self.install_path, self._executable_path)

    def is_installed(self) -> bool:
        return os.path.isdir(self.install_path)

    def install(self):
        _LOGGER.info("Installing %s %s", self.name, self.version)
        if not self._relocatable:
            _LOGGER.debug("Installing directly to final path")
            if os.path.exists(self.install_path):
                shutil.rmtree(self.install_path)
            try:
                self._installer.install(self.install_path)
            except Exception:
                shutil.rmtree(self.install_path)
                raise
        else:
            temp_install_dir = self.install_path + ".tmp"
            if os.path.exists(temp_install_dir):
                shutil.rmtree(temp_install_dir)
            try:
                self._installer.install(temp_install_dir)
                if os.path.exists(self.install_path):
                    shutil.rmtree(self.install_path)
                os.rename(temp_install_dir, self.install_path)
            except Exception:
                shutil.rmtree(temp_install_dir)
                raise
        for install_step in self._post_install:
            _LOGGER.info("Running post install step '%s'", " ".join(install_step))
            check_call(install_step, cwd=self.install_path)

    def ensure_installed(self):
        if not self.is_installed():
            self.install()


def find_app(tool, version=None):
    overrides = None
    if version:
        overrides = dict(apps=dict(tool=dict(version=version)))
    config = load_config(overrides)
    if tool in config['apps']:
        return App(tool, config)
    else:
        return None
