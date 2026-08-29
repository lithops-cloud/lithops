#
# (C) Copyright IBM Corp. 2021
# (C) Copyright Cloudlab URV 2021
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
import copy
import json
import importlib
import logging

from lithops import constants as c
from lithops.version import __version__
from lithops.utils import CURRENT_PY_VERSION, get_mode, get_default_backend

logger = logging.getLogger(__name__)

for _lithops_dir in (c.LITHOPS_TEMP_DIR, c.JOBS_DIR, c.LOGS_DIR, c.CLEANER_DIR):
    os.makedirs(_lithops_dir, exist_ok=True)

_USER_AGENT = f'lithops/{__version__}'
_LOCALHOST_FALLBACK = {
    'lithops': {
        'mode': c.LOCALHOST,
        'backend': c.LOCALHOST,
        'storage': c.LOCALHOST,
    }
}


def load_yaml_config(config_filename):
    """Reads a YAML config file, or returns nothing if it does not exist"""
    import yaml
    try:
        with open(config_filename, 'r') as config_file:
            data = yaml.safe_load(config_file)
    except FileNotFoundError:
        data = {}

    return data


def dump_yaml_config(config_filename, data):
    """Writes a config to a YAML file, creating its directory if needed"""
    import yaml
    dirname = os.path.dirname(config_filename)
    if dirname:
        os.makedirs(dirname, exist_ok=True)

    with open(config_filename, "w") as config_file:
        yaml.dump(data, config_file, default_flow_style=False)


def get_default_config_filename():
    """
    Resolve the default Lithops config file, in order:
    1. LITHOPS_CONFIG_FILE environment variable
    2. .lithops_config in the current working directory
    3. ~/.lithops/config
    4. /etc/lithops/config
    """
    if 'LITHOPS_CONFIG_FILE' in os.environ:
        return os.environ['LITHOPS_CONFIG_FILE']

    if os.path.exists(".lithops_config"):
        return os.path.abspath('.lithops_config')

    if os.path.exists(c.CONFIG_FILE):
        return c.CONFIG_FILE

    if os.path.exists(c.CONFIG_FILE_GLOBAL):
        return c.CONFIG_FILE_GLOBAL

    return None


def load_config(config_file=None, log=True):
    """
    Loads the configuration from a file, from the environment, or from the
    default locations. Falls back to localhost mode when there is none
    """
    config_data = None

    if config_file:
        config_filename = os.path.expanduser(config_file)
        if log:
            logger.debug(f"Loading configuration from {config_filename}")
        if not os.path.exists(config_filename):
            raise FileNotFoundError(
                f"Config file {config_filename} doesn't exist"
            )
        config_data = load_yaml_config(config_filename)

    elif 'LITHOPS_CONFIG' in os.environ:
        if log:
            logger.debug("Loading configuration from env LITHOPS_CONFIG")
        config_data = json.loads(os.environ['LITHOPS_CONFIG'])

    else:
        config_filename = get_default_config_filename()
        if config_filename:
            if log:
                logger.debug(f"Loading configuration from {config_filename}")
            config_data = load_yaml_config(config_filename)

    if not config_data:
        # None, {}, or empty YAML all mean "no usable config" → localhost.
        # A file containing `lithops: {}` is truthy and must NOT take this path.
        if log:
            logger.debug(
                "Config file not found. Setting Lithops to Localhost mode"
            )
        config_data = copy.deepcopy(_LOCALHOST_FALLBACK)

    return config_data


def _copy_or_load_config(config_file, config_data, **load_kwargs):
    # Treat None *and* {} as "no config provided" so callers fall back to
    # load_config(). This is intentional: an empty dict must not skip file/env
    # discovery (a long-standing default_config contract).
    copied = copy.deepcopy(config_data)
    return copied if copied else load_config(config_file, **load_kwargs)


def _ensure_lithops_section(config_data):
    if 'lithops' not in config_data or not config_data['lithops']:
        config_data['lithops'] = {}
    return config_data['lithops']


def _section_with_user_agent(config, backend):
    # Falsy sections ({}, None, missing) yield a *new* dict so the original
    # config is not mutated. A populated section is updated in place.
    section = config[backend] if backend in config and config[backend] else {}
    section['user_agent'] = _USER_AGENT
    return section


def get_log_info(config_file=None, config_data=None):
    """Returns the logging settings of a configuration, filling the defaults"""
    config_data = _copy_or_load_config(config_file, config_data, log=False)
    lithops_cfg = _ensure_lithops_section(config_data)

    lithops_cfg.setdefault('log_level', c.LOGGER_LEVEL)
    lithops_cfg.setdefault('log_format', c.LOGGER_FORMAT)
    lithops_cfg.setdefault('log_stream', c.LOGGER_STREAM)
    lithops_cfg.setdefault('log_filename', None)

    return (
        lithops_cfg['log_level'],
        lithops_cfg['log_format'],
        lithops_cfg['log_stream'],
        lithops_cfg['log_filename'],
    )


def _resolve_mode_and_backend(config_data):
    """
    Fills in the mode and the backend out of each other. When both are set the
    backend wins, and the mode is rewritten to the one it belongs to
    """
    lithops_cfg = config_data['lithops']
    backend = lithops_cfg.get('backend')
    mode = lithops_cfg.get('mode')

    if mode and not backend:
        if mode in config_data and 'backend' in config_data[mode]:
            lithops_cfg['backend'] = config_data[mode]['backend']
        else:
            lithops_cfg['backend'] = get_default_backend(mode)
    elif backend:
        lithops_cfg['mode'] = get_mode(backend)
    elif not backend and not mode:
        mode = lithops_cfg['mode'] = c.MODE_DEFAULT
        lithops_cfg['backend'] = get_default_backend(mode)

    return lithops_cfg.get('backend'), lithops_cfg.get('mode')


def _load_compute_backend_config(config_data, mode, backend):
    """Lets the config module of the compute backend fill in its own defaults"""
    if mode == c.LOCALHOST:
        logger.debug("Loading compute backend module: localhost")
        module_name = 'lithops.localhost.config'
    elif mode == c.SERVERLESS:
        logger.debug(f"Loading Serverless backend module: {backend}")
        module_name = f'lithops.serverless.backends.{backend}.config'
    elif mode == c.STANDALONE:
        logger.debug(f"Loading Standalone backend module: {backend}")
        module_name = f'lithops.standalone.backends.{backend}.config'
    else:
        return

    importlib.import_module(module_name).load_config(config_data)

    if mode == c.STANDALONE:
        # Standalone always runs one call per worker; user chunksize is ignored.
        config_data['lithops']['chunksize'] = 0


def default_config(
    config_file=None,
    config_data=None,
    config_overwrite=None,
    load_storage_config=True,
):
    """
    Build a complete Lithops configuration.

    Config is loaded from `config_data`, `config_file`, or the default file
    locations (see `get_default_config_filename`). Values in `config_overwrite`
    replace matching keys.
    """
    logger.info(f'Lithops v{__version__} - Python{CURRENT_PY_VERSION}')

    config_overwrite = config_overwrite or {}
    config_data = _copy_or_load_config(config_file, config_data)
    lithops_cfg = _ensure_lithops_section(config_data)

    if 'lithops' in config_overwrite:
        lithops_cfg.update(config_overwrite['lithops'])

    backend, mode = _resolve_mode_and_backend(config_data)

    if backend not in config_data or config_data[backend] is None:
        # Missing or None is replaced. An existing {} is kept (unlike the
        # lithops section, where an empty dict is also replaced).
        config_data[backend] = {}

    if 'backend' in config_overwrite and config_overwrite['backend']:
        config_data[backend].update(config_overwrite['backend'])

    _load_compute_backend_config(config_data, mode, backend)

    if 'chunksize' not in config_data['lithops']:
        config_data['lithops']['chunksize'] = (
            config_data[backend]['worker_processes']
        )

    if load_storage_config:
        config_data = default_storage_config(config_data=config_data)
        storage = config_data['lithops']['storage']
        if storage == c.LOCALHOST and backend != c.LOCALHOST:
            raise Exception(
                f'Localhost storage backend cannot be used with {backend}'
            )

    for key, value in c.LITHOPS_DEFAULT_CONFIG_KEYS.items():
        config_data['lithops'].setdefault(key, value)

    return config_data


def default_storage_config(config_file=None, config_data=None, backend=None):
    """
    Builds a Lithops configuration that only holds the storage backend, whose
    config module fills in its own defaults
    """
    config_data = _copy_or_load_config(config_file, config_data)
    lithops_cfg = _ensure_lithops_section(config_data)

    if 'storage' not in lithops_cfg:
        lithops_cfg['storage'] = c.STORAGE_BACKEND_DEFAULT

    if backend:
        lithops_cfg['storage'] = backend

    sb = lithops_cfg['storage']
    logger.debug(f"Loading Storage backend module: {sb}")
    importlib.import_module(
        f'lithops.storage.backends.{sb}.config'
    ).load_config(config_data)

    return config_data


def extract_storage_config(config):
    """Extracts the config that the storage backend of a job needs"""
    backend = config['lithops']['storage']
    return {
        'monitoring_interval': config['lithops'].get(
            'monitoring_interval',
            c.LITHOPS_DEFAULT_CONFIG_KEYS['monitoring_interval'],
        ),
        'backend': backend,
        backend: _section_with_user_agent(config, backend),
    }


def extract_localhost_config(config):
    """Extracts the config that the localhost compute backend needs"""
    return config[c.LOCALHOST].copy()


def extract_serverless_config(config):
    """Extracts the config that the serverless compute backend needs"""
    backend = config['lithops']['backend']
    return {
        'backend': backend,
        backend: _section_with_user_agent(config, backend),
    }


def extract_standalone_config(config):
    """Extracts the config that the standalone compute backend needs"""
    backend = config['lithops']['backend']
    sa_config = config[c.STANDALONE].copy()
    sa_config['backend'] = backend
    sa_config['storage'] = config['lithops'].get('storage')
    sa_config[backend] = _section_with_user_agent(config, backend)
    return sa_config
