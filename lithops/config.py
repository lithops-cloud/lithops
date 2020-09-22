#
# Copyright 2018 PyWren Team
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
import tempfile
import importlib
import logging.config
from lithops.version import __version__

logger = logging.getLogger(__name__)

COMPUTE_BACKEND_DEFAULT = 'ibm_cf'
STORAGE_BACKEND_DEFAULT = 'ibm_cos'

STORAGE_BASE_FOLDER = "lithops-data"
DOCKER_BASE_FOLDER = "lithops-docker"
TEMP = os.path.realpath(tempfile.gettempdir())
LITHOPS_TEMP = "~/lithops-temp"
STORAGE_FOLDER = os.path.join(TEMP, STORAGE_BASE_FOLDER)
DOCKER_FOLDER = os.path.join(TEMP, DOCKER_BASE_FOLDER)

JOBS_PREFIX = "lithops.jobs"
TEMP_PREFIX = "lithops.jobs/tmp"
LOGS_PREFIX = "lithops.logs"
RUNTIMES_PREFIX = "lithops.runtimes"


MAX_AGG_DATA_SIZE = 4  # 4MiB

HOME_DIR = os.path.expanduser('~')
CONFIG_DIR = os.path.join(HOME_DIR, '.lithops')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config')
CACHE_DIR = os.path.join(CONFIG_DIR, 'cache')


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

    # overwrite values provided by the user
    config_data['lithops'].update(config_overwrite)

    if 'storage_bucket' not in config_data['lithops']:
        raise Exception("storage_bucket is mandatory in lithops section of the configuration")

    if 'compute_backend' not in config_data['lithops']:
        config_data['lithops']['compute_backend'] = COMPUTE_BACKEND_DEFAULT
    if 'storage_backend' not in config_data['lithops']:
        config_data['lithops']['storage_backend'] = STORAGE_BACKEND_DEFAULT

    if 'rabbitmq' in config_data:
        if config_data['rabbitmq'] is None \
           or 'amqp_url' not in config_data['rabbitmq'] \
           or config_data['rabbitmq']['amqp_url'] is None:
            del config_data['rabbitmq']

    cb = config_data['lithops']['compute_backend']
    logger.debug("Loading Compute backend module: {}".format(cb))
    cb_config = importlib.import_module('lithops.compute.backends.{}.config'.format(cb))
    cb_config.load_config(config_data)

    sb = config_data['lithops']['storage_backend']
    logger.debug("Loading Storage backend module: {}".format(sb))
    sb_config = importlib.import_module('lithops.storage.backends.{}.config'.format(sb))
    sb_config.load_config(config_data)

    return config_data


def extract_storage_config(config):
    storage_config = dict()
    sb = config['lithops']['storage_backend']
    storage_config['backend'] = sb
    storage_config['bucket'] = config['lithops']['storage_bucket']

    storage_config[sb] = config[sb]
    storage_config[sb]['user_agent'] = 'lithops/{}'.format(__version__)
    if 'storage_backend_region' in config['lithops']:
        storage_config[sb]['region'] = config['lithops']['storage_backend_region']

    return storage_config


def extract_compute_config(config):
    compute_config = dict()
    cb = config['lithops']['compute_backend']
    compute_config['backend'] = cb

    compute_config[cb] = config[cb]
    compute_config[cb]['user_agent'] = 'lithops/{}'.format(__version__)
    if 'compute_backend_region' in config['lithops']:
        compute_config[cb]['region'] = config['lithops']['compute_backend_region']
    if 'remote_client' in config['lithops']:
        remote_client_backend = config['lithops']['remote_client']
        remote_client_config = importlib.import_module('lithops.libs.clients.{}.config'
                                                       .format(remote_client_backend))
        remote_client_config.load_config(config)

        remote_client_config = config[remote_client_backend]
        compute_config[remote_client_backend] = remote_client_config
        compute_config['remote_client'] = config['lithops']['remote_client']

    return compute_config


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
