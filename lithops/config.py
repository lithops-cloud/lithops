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
from lithops.utils import verify_runtime_name, get_mode, get_default_backend
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
    """
    if 'LITHOPS_CONFIG_FILE' in os.environ:
        config_filename = os.environ['LITHOPS_CONFIG_FILE']

    elif os.path.exists(".lithops_config"):
        config_filename = os.path.abspath('.lithops_config')

    else:
        config_filename = c.CONFIG_FILE
        if not os.path.exists(config_filename):
            return None

    return config_filename


def load_config(log=True):
    """ Load the configuration """
    config_data = None
    if 'LITHOPS_CONFIG' in os.environ:
        if log:
            logger.debug("Loading configuration from env LITHOPS_CONFIG")
        config_data = json.loads(os.environ.get('LITHOPS_CONFIG'))
    else:
        config_filename = get_default_config_filename()
        if config_filename:
            if log:
                logger.debug("Loading configuration from {}".format(config_filename))
            config_data = load_yaml_config(config_filename)

    if not config_data:
        # Set to Localhost mode
        if log:
            logger.debug("Config file not found")
        config_data = {'lithops': {'mode': c.LOCALHOST,
                                   'backend': c.LOCALHOST,
                                   'storage': c.LOCALHOST}}

    return config_data


def get_log_info(config_data=None):
    """ Return lithops logging information set in configuration """
    config_data = copy.deepcopy(config_data) or load_config(log=False)

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


def default_config(config_data=None, config_overwrite={}, load_storage_config=True):
    """
    First checks .lithops_config
    then checks LITHOPS_CONFIG_FILE environment variable
    then ~/.lithops/config
    """
    logger.info('Lithops v{}'.format(__version__))

    config_data = copy.deepcopy(config_data) or load_config()

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

    if 'backend' in config_overwrite:
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

        verify_runtime_name(config_data[backend]['runtime'])

    elif mode == c.SERVERLESS:
        logger.debug("Loading Serverless backend module: {}".format(backend))
        cb_config = importlib.import_module('lithops.serverless.backends.{}.config'.format(backend))
        cb_config.load_config(config_data)

        verify_runtime_name(config_data[backend]['runtime'])

    elif mode == c.STANDALONE:
        if c.STANDALONE not in config_data or \
           config_data[c.STANDALONE] is None:
            config_data[c.STANDALONE] = {}

        if 'runtime' in config_data[backend]:
            config_data[c.STANDALONE]['runtime'] = config_data[backend]['runtime']

        if 'exec_mode' not in config_data[c.STANDALONE]:
            config_data[c.STANDALONE]['exec_mode'] = c.SA_EXEC_MODE
        if 'start_timeout' not in config_data[c.STANDALONE]:
            config_data[c.STANDALONE]['start_timeout'] = c.SA_START_TIMEOUT
        if 'pull_runtime' not in config_data[c.STANDALONE]:
            config_data[c.STANDALONE]['pull_runtime'] = c.SA_PULL_RUNTIME
        if 'auto_dismantle' not in config_data[c.STANDALONE]:
            config_data[c.STANDALONE]['auto_dismantle'] = c.SA_AUTO_DISMANTLE
        if 'soft_dismantle_timeout' not in config_data[c.STANDALONE]:
            config_data[c.STANDALONE]['soft_dismantle_timeout'] = c.SA_SOFT_DISMANTLE_TIMEOUT
        if 'hard_dismantle_timeout' not in config_data[c.STANDALONE]:
            config_data[c.STANDALONE]['hard_dismantle_timeout'] = c.SA_HARD_DISMANTLE_TIMEOUT

        logger.debug("Loading Standalone backend module: {}".format(backend))
        sb_config = importlib.import_module('lithops.standalone.backends.{}.config'.format(backend))
        sb_config.load_config(config_data)

        if 'runtime' not in config_data[c.STANDALONE]:
            config_data[c.STANDALONE]['runtime'] = c.SA_RUNTIME

        verify_runtime_name(config_data[c.STANDALONE]['runtime'])

    if 'monitoring' not in config_data['lithops']:
        config_data['lithops']['monitoring'] = c.MONITORING_DEFAULT

    if 'execution_timeout' not in config_data['lithops']:
        config_data['lithops']['execution_timeout'] = c.EXECUTION_TIMEOUT_DEFAULT

    if 'chunksize' not in config_data['lithops']:
        config_data['lithops']['chunksize'] = config_data[backend]['worker_processes']

    if load_storage_config:
        config_data = default_storage_config(config_data)
        if config_data['lithops']['storage'] == c.LOCALHOST \
           and backend != c.LOCALHOST:
            raise Exception(f'Localhost storage backend cannot be used with {backend}')

    return config_data


def default_storage_config(config_data=None, backend=None):
    """ Function to load default storage config """

    config_data = copy.deepcopy(config_data) or load_config()

    if 'lithops' not in config_data or not config_data['lithops']:
        config_data['lithops'] = {}

    if 'storage' not in config_data['lithops']:
        config_data['lithops']['storage'] = c.STORAGE_BACKEND_DEFAULT

    if backend:
        config_data['lithops']['storage'] = backend

    sb = config_data['lithops']['storage']
    logger.debug("Loading Storage backend module: {}".format(sb))
    sb_config = importlib.import_module('lithops.storage.backends.{}.config'.format(sb))
    sb_config.load_config(config_data)

    if 'storage_bucket' not in config_data['lithops']:
        raise Exception("storage_bucket is mandatory in "
                        "lithops section of the configuration")

    return config_data


def extract_storage_config(config):
    storage_config = {}
    sb = config['lithops']['storage']
    storage_config['backend'] = sb
    storage_config['bucket'] = config['lithops']['storage_bucket']
    storage_config[sb] = config[sb]
    storage_config[sb]['user_agent'] = 'lithops/{}'.format(__version__)

    if 'storage_region' in config['lithops']:
        storage_config[sb]['region'] = config['lithops']['storage_region']

    return storage_config


def extract_localhost_config(config):
    localhost_config = config[c.LOCALHOST].copy()

    return localhost_config


def extract_serverless_config(config):
    sl_config = {}
    backend = config['lithops']['backend']
    sl_config['backend'] = backend
    sl_config[backend] = config[backend] if backend in config and config[backend] else {}
    sl_config[backend]['user_agent'] = 'lithops/{}'.format(__version__)

    return sl_config


def extract_standalone_config(config):
    sa_config = config[c.STANDALONE].copy()
    backend = config['lithops']['backend']
    sa_config['backend'] = backend
    sa_config[backend] = config[backend] if backend in config and config[backend] else {}
    sa_config[backend]['runtime'] = sa_config['runtime']
    sa_config[backend]['user_agent'] = 'lithops/{}'.format(__version__)

    return sa_config
