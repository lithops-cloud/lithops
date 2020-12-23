#
# (C) Copyright IBM Corp. 2019
# (C) Copyright Cloudlab URV 2020
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
import json
import importlib
import logging
import multiprocessing as mp
import lithops.constants as constants
from lithops.version import __version__
from lithops.utils import verify_runtime_name

logger = logging.getLogger(__name__)


def load_yaml_config(config_filename):
    import yaml

    with open(config_filename, 'r') as config_file:
        data = yaml.safe_load(config_file)

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
        config_filename = constants.CONFIG_FILE
        if not os.path.exists(config_filename):
            return None

    return config_filename


def load_config():
    """ Load the configuration """
    if 'LITHOPS_CONFIG' in os.environ:
        config_data = json.loads(os.environ.get('LITHOPS_CONFIG'))
    else:
        config_filename = get_default_config_filename()
        if config_filename:
            config_data = load_yaml_config(config_filename)
        else:
            # No config file found. Set to Localhost mode
            config_data = {'lithops': {'mode': constants.LOCALHOST,
                                       'storage': constants.LOCALHOST}}

    return config_data


def get_mode(config_data=None):
    """ Return lithops execution mode set in configuration """
    config_data = config_data or load_config()

    if 'lithops' not in config_data or not config_data['lithops']:
        config_data['lithops'] = {}

    if 'mode' not in config_data['lithops']:
        config_data['lithops']['mode'] = constants.MODE_DEFAULT

    return config_data['lithops']['mode']


def default_config(config_data=None, config_overwrite={}):
    """
    First checks .lithops_config
    then checks LITHOPS_CONFIG_FILE environment variable
    then ~/.lithops/config
    """
    logger.info('Lithops v{}'.format(__version__))
    logger.debug("Loading configuration")

    config_data = config_data or load_config()

    if 'lithops' not in config_data or not config_data['lithops']:
        config_data['lithops'] = {}

    if 'mode' not in config_data['lithops']:
        config_data['lithops']['mode'] = constants.MODE_DEFAULT

    if 'execution_timeout' not in config_data['lithops']:
        config_data['lithops']['execution_timeout'] = constants.EXECUTION_TIMEOUT_DEFAULT

    # overwrite values provided by the user
    if 'lithops' in config_overwrite:
        config_data['lithops'].update(config_overwrite['lithops'])

    if constants.LOCALHOST in config_overwrite:
        if constants.LOCALHOST not in config_data or \
           config_data[constants.LOCALHOST] is None:
            config_data[constants.LOCALHOST] = {}
        config_data[constants.LOCALHOST].update(config_overwrite[constants.LOCALHOST])

    if constants.SERVERLESS in config_overwrite:
        if constants.SERVERLESS not in config_data or \
           config_data[constants.SERVERLESS] is None:
            config_data[constants.SERVERLESS] = {}
        config_data[constants.SERVERLESS].update(config_overwrite[constants.SERVERLESS])

    if constants.STANDALONE in config_overwrite:
        if constants.STANDALONE not in config_data or \
           config_data[constants.STANDALONE] is None:
            config_data[constants.STANDALONE] = {}
        config_data[constants.STANDALONE].update(config_overwrite[constants.STANDALONE])

    if config_data['lithops']['mode'] == constants.SERVERLESS:
        if constants.SERVERLESS not in config_data or \
           config_data[constants.SERVERLESS] is None:
            config_data[constants.SERVERLESS] = {}

        if 'backend' not in config_data[constants.SERVERLESS]:
            config_data[constants.SERVERLESS]['backend'] = constants.SERVERLESS_BACKEND_DEFAULT

        sb = config_data[constants.SERVERLESS]['backend']
        logger.debug("Loading Serverless backend module: {}".format(sb))
        cb_config = importlib.import_module('lithops.serverless.backends.{}.config'.format(sb))
        cb_config.load_config(config_data)

        verify_runtime_name(config_data[constants.SERVERLESS]['runtime'])

    elif config_data['lithops']['mode'] == constants.STANDALONE:
        if constants.STANDALONE not in config_data or \
           config_data[constants.STANDALONE] is None:
            config_data[constants.STANDALONE] = {}

        if 'auto_dismantle' not in config_data[constants.STANDALONE]:
            config_data[constants.STANDALONE]['auto_dismantle'] = constants.STANDALONE_AUTO_DISMANTLE_DEFAULT
        if 'soft_dismantle_timeout' not in config_data[constants.STANDALONE]:
            config_data[constants.STANDALONE]['soft_dismantle_timeout'] = constants.STANDALONE_SOFT_DISMANTLE_TIMEOUT_DEFAULT
        if 'hard_dismantle_timeout' not in config_data[constants.STANDALONE]:
            config_data[constants.STANDALONE]['hard_dismantle_timeout'] = constants.STANDALONE_HARD_DISMANTLE_TIMEOUT_DEFAULT
        if 'backend' not in config_data[constants.STANDALONE]:
            config_data[constants.STANDALONE]['backend'] = constants.STANDALONE_BACKEND_DEFAULT
        if 'runtime' not in config_data[constants.STANDALONE]:
            config_data[constants.STANDALONE]['runtime'] = constants.STANDALONE_RUNTIME_DEFAULT

        sb = config_data[constants.STANDALONE]['backend']
        logger.debug("Loading Standalone backend module: {}".format(sb))
        sb_config = importlib.import_module('lithops.standalone.backends.{}.config'.format(sb))
        sb_config.load_config(config_data)

        verify_runtime_name(config_data[constants.STANDALONE]['runtime'])

    elif config_data['lithops']['mode'] == constants.LOCALHOST:
        if 'workers' not in config_data['lithops']:
            config_data['lithops']['workers'] = mp.cpu_count()
        if constants.LOCALHOST not in config_data or \
           config_data[constants.LOCALHOST] is None:
            config_data[constants.LOCALHOST] = {}
        if 'runtime' not in config_data[constants.LOCALHOST]:
            config_data[constants.LOCALHOST]['runtime'] = constants.LOCALHOST_RUNTIME_DEFAULT
        logger.debug("Loading compute backend module: localhost")

        verify_runtime_name(config_data[constants.LOCALHOST]['runtime'])

    return default_storage_config(config_data)


def default_storage_config(config_data=None, backend=None):
    """ Function to load default storage config """

    config_data = config_data or load_config()

    if 'lithops' not in config_data or not config_data['lithops']:
        config_data['lithops'] = {}

    if 'mode' not in config_data['lithops']:
        config_data['lithops']['mode'] = constants.MODE_DEFAULT

    if 'storage' not in config_data['lithops']:
        config_data['lithops']['storage'] = constants.STORAGE_BACKEND_DEFAULT

    if backend:
        config_data['lithops']['storage'] = backend

    if config_data['lithops']['storage'] == constants.LOCALHOST:
        config_data['lithops']['storage_bucket'] = 'storage'
    else:
        if 'storage_bucket' not in config_data['lithops']:
            raise Exception("storage_bucket is mandatory in "
                            "lithops section of the configuration")

    mode = config_data['lithops']['mode']
    storage = config_data['lithops']['storage']
    if storage == constants.LOCALHOST and mode != constants.LOCALHOST:
        raise Exception('Localhost storage backend cannot run in {} mode'.format(mode))

    sb = config_data['lithops']['storage']
    logger.debug("Loading Storage backend module: {}".format(sb))
    sb_config = importlib.import_module('lithops.storage.backends.{}.config'.format(sb))
    sb_config.load_config(config_data)

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
    localhost_config = config[constants.LOCALHOST].copy()

    return localhost_config


def extract_serverless_config(config):
    serverless_config = config[constants.SERVERLESS].copy()
    sb = config[constants.SERVERLESS]['backend']
    serverless_config[sb] = config[sb] if sb in config and config[sb] else {}
    serverless_config[sb]['user_agent'] = 'lithops/{}'.format(__version__)

    if 'region' in config[constants.SERVERLESS]:
        serverless_config[sb]['region'] = config[constants.SERVERLESS]['region']

    return serverless_config


def extract_standalone_config(config):
    standalone_config = config[constants.STANDALONE].copy()
    sb = config[constants.STANDALONE]['backend']
    standalone_config[sb] = config[sb] if sb in config and config[sb] else {}
    standalone_config[sb]['user_agent'] = 'lithops/{}'.format(__version__)

    if 'region' in config[constants.STANDALONE]:
        standalone_config[sb]['region'] = config[constants.STANDALONE]['region']

    return standalone_config
