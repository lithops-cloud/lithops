#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import os
import posixpath
import re
import sys
from enum import Enum
from typing import Any, Dict

from lithops.version import __version__


DEFAULT_CONFIG_KEYS = {
    'runtime': os.path.basename(sys.executable),
    'worker_processes': os.cpu_count() or 1,
}

LOCALHOST_EXECUTION_TIMEOUT = 3600

_WINDOWS_PATH = re.compile(r'^[A-Za-z]:\\.*$')
# Interpreters like python, python3, python3.12, python.exe — not docker tags
# such as python:3.12.
_PYTHON_INTERPRETER = re.compile(
    r'^python(\d+(\.\d+)*)?(\.exe)?$',
    re.IGNORECASE,
)


class LocalhostEnvironment(Enum):
    """Where a localhost job runs: this Python installation or a container"""
    DEFAULT = "default"
    CONTAINER = "container"


def get_environment(runtime_name: str) -> LocalhostEnvironment:
    """
    Decides the environment a runtime name refers to. An absolute path or an
    interpreter name is run locally, anything else is a container image
    """
    basename = os.path.basename(runtime_name)
    if (
        runtime_name.startswith('/')
        or _WINDOWS_PATH.match(runtime_name) is not None
        or _PYTHON_INTERPRETER.match(basename) is not None
    ):
        return LocalhostEnvironment.DEFAULT
    return LocalhostEnvironment.CONTAINER


def runtime_key(runtime_name: str) -> str:
    """
    Builds the key the runtime metadata is cached under. Always POSIX, so that
    a Windows client and a Unix one agree on the same key
    """
    name = runtime_name.replace('\\', '/').strip('/')
    return posixpath.join('localhost', __version__, name)


def runtime_info(config: Dict[str, Any]) -> Dict[str, Any]:
    """Returns the runtime limits the executor reports to the user"""
    return {
        'runtime_name': config['runtime'],
        'runtime_memory': config.get('runtime_memory'),
        'runtime_timeout': config.get('runtime_timeout'),
        'max_workers': config['max_workers'],
    }


def load_config(config_data: Dict[str, Any]) -> None:
    """Fills in the localhost defaults that the user did not provide"""
    if 'localhost' not in config_data or not config_data['localhost']:
        config_data['localhost'] = {}

    for key, value in DEFAULT_CONFIG_KEYS.items():
        config_data['localhost'].setdefault(key, value)

    # This machine is the only worker, whatever the user configured
    config_data['localhost']['max_workers'] = 1

    lithops_cfg = config_data.setdefault('lithops', {})
    lithops_cfg.setdefault('execution_timeout', LOCALHOST_EXECUTION_TIMEOUT)
    lithops_cfg.setdefault('storage', 'localhost')
