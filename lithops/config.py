#
# Copyright 2018 PyWren Team
# Copyright Cloudlab URV 2020
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
import tempfile
import logging.config
from lithops.version import __version__

logger = logging.getLogger(__name__)


EXECUTOR_DEFAULT = 'serverless'
SERVERLESS_BACKEND_DEFAULT = 'ibm_cf'
STANDALONE_BACKEND_DEFAULT = 'ibm_vpc'
STORAGE_BACKEND_DEFAULT = 'ibm_cos'

JOBS_PREFIX = "lithops.jobs"
TEMP_PREFIX = "lithops.jobs/tmp"
LOGS_PREFIX = "lithops.logs"
RUNTIMES_PREFIX = "lithops.runtimes"

EXECUTION_TIMEOUT_DEFAULT = 1800

STANDALONE_RUNTIME_DEFAULT = 'python3'
STANDALONE_AUTO_DISMANTLE_DEFAULT = True
STANDALONE_SOFT_DISMANTLE_TIMEOUT_DEFAULT = 300
STANDALONE_HARD_DISMANTLE_TIMEOUT_DEFAULT = 3600

MAX_AGG_DATA_SIZE = 4  # 4MiB

TEMP = os.path.realpath(tempfile.gettempdir())
STORAGE_DIR = os.path.join(TEMP, 'lithops')
JOBS_DONE_DIR = os.path.join(STORAGE_DIR, 'jobs')
REMOTE_INSTALL_DIR = '/opt/lithops'

HOME_DIR = os.path.expanduser('~')
CONFIG_DIR = os.path.join(HOME_DIR, '.lithops')
CACHE_DIR = os.path.join(CONFIG_DIR, 'cache')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config')


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


def get_default_home_filename():
    default_home_filename = CONFIG_FILE
    if not os.path.exists(default_home_filename):
        default_home_filename = os.path.join(HOME_DIR, '.lithops_config')

    return default_home_filename


def get_default_config_filename():
    """
    First checks .lithops_config
    then checks LITHOPS_CONFIG_FILE environment variable
    then ~/.lithops_config
    """
    if 'LITHOPS_CONFIG_FILE' in os.environ:
        config_filename = os.environ['LITHOPS_CONFIG_FILE']

    elif os.path.exists(".lithops_config"):
        config_filename = os.path.abspath('.lithops_config')

    else:
        config_filename = get_default_home_filename()

    logger.info('Getting configuration from {}'.format(config_filename))

    return config_filename


def default_config(config_data=None, config_overwrite={}):
    """
    First checks .lithops_config
    then checks LITHOPS_CONFIG_FILE environment variable
    then ~/.lithops_config
    """
    logger.info('Lithops v{}'.format(__version__))
    logger.debug("Loading configuration")

    if not config_data:
        if 'LITHOPS_CONFIG' in os.environ:
            config_data = json.loads(os.environ.get('LITHOPS_CONFIG'))
        else:
            config_filename = get_default_config_filename()
            if config_filename is None:
                raise ValueError("could not find configuration file")
            config_data = load_yaml_config(config_filename)

    if 'lithops' not in config_data:
        raise Exception("lithops section is mandatory in configuration")
    if 'storage_bucket' not in config_data['lithops']:
        raise Exception("storage_bucket is mandatory in lithops section of the configuration")

    # overwrite values provided by the user
    if 'lithops' in config_overwrite:
        config_data['lithops'].update(config_overwrite['lithops'])
    if 'localhost' in config_overwrite:
        if 'localhost' not in config_data:
            config_data['localhost'] = {}
        config_data['localhost'].update(config_overwrite['localhost'])
    if 'serverless' in config_overwrite:
        if 'serverless' not in config_data:
            config_data['serverless'] = {}
        config_data['serverless'].update(config_overwrite['serverless'])
    if 'standalone' in config_overwrite:
        if 'standalone' not in config_data:
            config_data['standalone'] = {}
        config_data['standalone'].update(config_overwrite['standalone'])

    if 'executor' not in config_data['lithops']:
        config_data['lithops']['executor'] = EXECUTOR_DEFAULT
    if 'execution_timeout' not in config_data['lithops']:
        config_data['lithops']['execution_timeout'] = EXECUTION_TIMEOUT_DEFAULT

    if config_data['lithops']['executor'] == 'serverless':
        if 'serverless' not in config_data:
            config_data['serverless'] = {}
        if 'backend' not in config_data['serverless']:
            config_data['serverless']['backend'] = SERVERLESS_BACKEND_DEFAULT

        sb = config_data['serverless']['backend']
        logger.debug("Loading Serverless backend module: {}".format(sb))
        cb_config = importlib.import_module('lithops.serverless.backends.{}.config'.format(sb))
        cb_config.load_config(config_data)

    elif config_data['lithops']['executor'] == 'standalone':
        if 'standalone' not in config_data:
            config_data['standalone'] = {}
        if 'auto_dismantle' not in config_data['standalone']:
            config_data['standalone']['auto_dismantle'] = STANDALONE_AUTO_DISMANTLE_DEFAULT
        if 'soft_dismantle_timeout' not in config_data['standalone']:
            config_data['standalone']['soft_dismantle_timeout'] = STANDALONE_SOFT_DISMANTLE_TIMEOUT_DEFAULT
        if 'hard_dismantle_timeout' not in config_data['standalone']:
            config_data['standalone']['hard_dismantle_timeout'] = STANDALONE_HARD_DISMANTLE_TIMEOUT_DEFAULT
        if 'backend' not in config_data['standalone']:
            config_data['standalone']['backend'] = STANDALONE_BACKEND_DEFAULT
        if 'runtime' not in config_data['standalone']:
            config_data['standalone']['runtime'] = STANDALONE_RUNTIME_DEFAULT

        sb = config_data['standalone']['backend']
        logger.debug("Loading Standalone backend module: {}".format(sb))
        sb_config = importlib.import_module('lithops.standalone.backends.{}.config'.format(sb))
        sb_config.load_config(config_data)

    elif config_data['lithops']['executor'] == 'localhost':
        if 'runtime' not in config_data['localhost']:
            config_data['localhost']['runtime'] = 'python3'

    if 'storage' not in config_data['lithops']:
        config_data['lithops']['storage'] = STORAGE_BACKEND_DEFAULT
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
    localhost_config = config['localhost'].copy()

    return localhost_config


def extract_serverless_config(config):
    serverless_config = config['serverless'].copy()
    sb = config['serverless']['backend']
    serverless_config[sb] = config[sb]
    serverless_config[sb]['user_agent'] = 'lithops/{}'.format(__version__)

    if 'region' in config['serverless']:
        serverless_config[sb]['region'] = config['serverless']['region']

    return serverless_config


def extract_standalone_config(config):
    standalone_config = config['standalone'].copy()
    sb = config['standalone']['backend']
    standalone_config[sb] = config[sb]
    standalone_config[sb]['user_agent'] = 'lithops/{}'.format(__version__)

    if 'region' in config['standalone']:
        standalone_config[sb]['region'] = config['standalone']['region']

    return standalone_config


def default_logging_config(log_level='INFO'):
    if log_level == 'DEBUG_BOTO3':
        log_level = 'DEBUG'
        logging.getLogger('ibm_boto3').setLevel(logging.DEBUG)
        logging.getLogger('ibm_botocore').setLevel(logging.DEBUG)

    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
            },
        },
        'handlers': {
            'default': {
                'level': log_level,
                'class': 'logging.StreamHandler',
                'formatter': 'standard'
            },
        },
        'loggers': {
            '': {
                'handlers': ['default'],
                'level': log_level,
                'propagate': True
            }
        }
    })


def cloud_logging_config(log_level='INFO'):
    if log_level == 'DEBUG_BOTO3':
        log_level = 'DEBUG'
        logging.getLogger('ibm_boto3').setLevel(logging.DEBUG)
        logging.getLogger('ibm_botocore').setLevel(logging.DEBUG)

    if log_level == 'WARNING':
        log_level = 'INFO'

    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '[%(levelname)s] %(name)s: %(message)s'
            },
        },
        'handlers': {
            'default': {
                'level': log_level,
                'class': 'logging.StreamHandler',
                'formatter': 'standard',
                'stream': 'ext://sys.stdout'
            },
        },
        'loggers': {
            '': {
                'handlers': ['default'],
                'level': log_level,
                'propagate': True
            }
        }
    })
