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
from builtins import FileNotFoundError

logger = logging.getLogger(__name__)

os.makedirs(c.LITHOPS_TEMP_DIR, exist_ok=True)
os.makedirs(c.JOBS_DIR, exist_ok=True)
os.makedirs(c.LOGS_DIR, exist_ok=True)
os.makedirs(c.CLEANER_DIR, exist_ok=True)

CPU_COUNT = os.cpu_count()


def load_yaml_config(config_filename):
    import yaml
    try:
        with open(config_filename, 'r') as config_file:
            data = yaml.safe_load(config_file)
    except FileNotFoundError:
        data = {}

    return data


def dump_yaml_config(config_filename, data):
    import yaml
    if not os.path.exists(os.path.dirname(config_filename)):
        os.makedirs(os.path.dirname(config_filename))

    with open(config_filename, "w") as config_file:
        yaml.dump(data, config_file, default_flow_style=False)


def get_default_config_filename():
    """
    First checks .lithops_config
    then checks LITHOPS_CONFIG_FILE environment variable
    then ~/.lithops/config
    and as last resort the global configuration /etc/lithops/config
    """
    if 'LITHOPS_CONFIG_FILE' in os.environ:
        config_filename = os.environ['LITHOPS_CONFIG_FILE']

    elif os.path.exists(".lithops_config"):
        config_filename = os.path.abspath('.lithops_config')

    else:
        config_filename = c.CONFIG_FILE
        if not os.path.exists(config_filename):
            config_filename = c.CONFIG_FILE_GLOBAL
            if not os.path.exists(config_filename):
                return None

    return config_filename


def load_config(config_file=None, log=True):
    """ Load the configuration """
    config_data = None

    if config_file:
        config_filename = os.path.expanduser(config_file)
        if log:
            logger.debug(f"Loading configuration from {config_filename}")
        if not os.path.exists(config_filename):
            raise FileNotFoundError(f"Config file {config_filename} doesn't exist")
        config_data = load_yaml_config(config_filename)

    elif 'LITHOPS_CONFIG' in os.environ:
        if log:
            logger.debug("Loading configuration from env LITHOPS_CONFIG")
        config_data = json.loads(os.environ.get('LITHOPS_CONFIG'))

    else:
        config_filename = get_default_config_filename()
        if config_filename:
            if log:
                logger.debug(f"Loading configuration from {config_filename}")
            config_data = load_yaml_config(config_filename)

    if not config_data:  # Set Lithops to Localhost mode
        if log:
            logger.debug("Config file not found. Setting Lithops to Localhost mode")
        config_data = {'lithops': {'mode': c.LOCALHOST, 'backend': c.LOCALHOST, 'storage': c.LOCALHOST}}

    return config_data


def get_log_info(config_file=None, config_data=None):
    """ Return lithops logging information set in configuration """
    config_data = copy.deepcopy(config_data) or load_config(config_file, log=False)

    if 'lithops' not in config_data or not config_data['lithops']:
        config_data['lithops'] = {}

    cl = config_data['lithops']

    if 'log_level' not in cl:
        cl['log_level'] = c.LOGGER_LEVEL
    if 'log_format' not in cl:
        cl['log_format'] = c.LOGGER_FORMAT
    if 'log_stream' not in cl:
        cl['log_stream'] = c.LOGGER_STREAM
    if 'log_filename' not in cl:
        cl['log_filename'] = None

    return cl['log_level'], cl['log_format'], cl['log_stream'], cl['log_filename']


def default_config(config_file=None, config_data=None, config_overwrite={}, load_storage_config=True):
    """
    First checks .lithops_config
    then checks LITHOPS_CONFIG_FILE environment variable
    then ~/.lithops/config
    """
    logger.info(f'Lithops v{__version__} - Python{CURRENT_PY_VERSION}')

    config_data = copy.deepcopy(config_data) or load_config(config_file)

    if 'lithops' not in config_data or not config_data['lithops']:
        config_data['lithops'] = {}

    # overwrite values provided by the user
    if 'lithops' in config_overwrite:
        config_data['lithops'].update(config_overwrite['lithops'])

    backend = config_data['lithops'].get('backend')
    mode = config_data['lithops'].get('mode')

    if mode and not backend:
        if mode in config_data and 'backend' in config_data[mode]:
            config_data['lithops']['backend'] = config_data[mode]['backend']
        else:
            config_data['lithops']['backend'] = get_default_backend(mode)
    elif backend:
        config_data['lithops']['mode'] = get_mode(backend)
    elif not backend and not mode:
        mode = config_data['lithops']['mode'] = c.MODE_DEFAULT
        config_data['lithops']['backend'] = get_default_backend(mode)

    backend = config_data['lithops'].get('backend')
    mode = config_data['lithops'].get('mode')

    if backend not in config_data or config_data[backend] is None:
        config_data[backend] = {}

    if 'backend' in config_overwrite and config_overwrite['backend']:
        config_data[backend].update(config_overwrite['backend'])

    if mode == c.LOCALHOST:
        logger.debug("Loading compute backend module: localhost")

        config_data[backend]['max_workers'] = 1

        if 'execution_timeout' not in config_data['lithops']:
            config_data['lithops']['execution_timeout'] = c.EXECUTION_TIMEOUT_LOCALHOST_DEFAULT

        if 'storage' not in config_data['lithops']:
            config_data['lithops']['storage'] = c.LOCALHOST

        if 'worker_processes' not in config_data[c.LOCALHOST]:
            config_data[backend]['worker_processes'] = CPU_COUNT

        if 'runtime' not in config_data[c.LOCALHOST]:
            config_data[backend]['runtime'] = c.LOCALHOST_RUNTIME_DEFAULT

    elif mode == c.SERVERLESS:
        logger.debug(f"Loading Serverless backend module: {backend}")
        cb_config = importlib.import_module(f'lithops.serverless.backends.{backend}.config')
        cb_config.load_config(config_data)

    elif mode == c.STANDALONE:
        logger.debug(f"Loading Standalone backend module: {backend}")
        sb_config = importlib.import_module(f'lithops.standalone.backends.{backend}.config')
        sb_config.load_config(config_data)

    if 'monitoring' not in config_data['lithops']:
        config_data['lithops']['monitoring'] = c.MONITORING_DEFAULT

    if 'execution_timeout' not in config_data['lithops']:
        config_data['lithops']['execution_timeout'] = c.EXECUTION_TIMEOUT_DEFAULT

    if 'chunksize' not in config_data['lithops']:
        config_data['lithops']['chunksize'] = config_data[backend]['worker_processes']

    if load_storage_config:
        config_data = default_storage_config(config_data=config_data)
        if config_data['lithops']['storage'] == c.LOCALHOST \
           and backend != c.LOCALHOST:
            raise Exception(f'Localhost storage backend cannot be used with {backend}')

    return config_data


def default_storage_config(config_file=None, config_data=None, backend=None):
    """ Function to load default storage config """

    config_data = copy.deepcopy(config_data) or load_config(config_file)

    if 'lithops' not in config_data or not config_data['lithops']:
        config_data['lithops'] = {}

    if 'storage' not in config_data['lithops']:
        config_data['lithops']['storage'] = c.STORAGE_BACKEND_DEFAULT

    if backend:
        config_data['lithops']['storage'] = backend

    sb = config_data['lithops']['storage']
    logger.debug(f"Loading Storage backend module: {sb}")
    sb_config = importlib.import_module(f'lithops.storage.backends.{sb}.config')
    sb_config.load_config(config_data)

    return config_data


def extract_storage_config(config):
    s_config = {}
    backend = config['lithops']['storage']
    s_config['backend'] = backend
    s_config[backend] = config[backend] if backend in config and config[backend] else {}
    s_config[backend]['user_agent'] = f'lithops/{__version__}'

    s_config['bucket'] = s_config[backend].get('storage_bucket')

    return s_config


def extract_localhost_config(config):
    localhost_config = config[c.LOCALHOST].copy()

    return localhost_config


def extract_serverless_config(config):
    sl_config = {}
    backend = config['lithops']['backend']
    sl_config['backend'] = backend
    sl_config[backend] = config[backend] if backend in config and config[backend] else {}
    sl_config[backend]['user_agent'] = f'lithops/{__version__}'

    return sl_config


def extract_standalone_config(config):
    sa_config = config[c.STANDALONE].copy()
    backend = config['lithops']['backend']
    sa_config['backend'] = backend
    sa_config[backend] = config[backend] if backend in config and config[backend] else {}
    sa_config[backend]['user_agent'] = f'lithops/{__version__}'

    return sa_config
