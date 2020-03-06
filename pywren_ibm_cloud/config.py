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
import importlib
import logging.config
from pywren_ibm_cloud.version import __version__

logger = logging.getLogger(__name__)

COMPUTE_BACKEND_DEFAULT = 'ibm_cf'
STORAGE_BACKEND_DEFAULT = 'ibm_cos'
JOBS_PREFIX = "pywren.jobs"
LOGS_PREFIX = "pywren.logs"
RUNTIMES_PREFIX = "pywren.runtimes"
MAX_AGG_DATA_SIZE = 4e6  # 4MB

HOME_DIR = os.path.expanduser('~')
CONFIG_DIR = os.path.join(HOME_DIR, '.pywren')
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
        default_home_filename = os.path.join(HOME_DIR, '.pywren_config')

    return default_home_filename


def get_default_config_filename():
    """
    First checks .pywren_config
    then checks PYWREN_CONFIG_FILE environment variable
    then ~/.pywren_config
    """
    if 'PYWREN_CONFIG_FILE' in os.environ:
        config_filename = os.environ['PYWREN_CONFIG_FILE']

    elif os.path.exists(".pywren_config"):
        config_filename = os.path.abspath('.pywren_config')

    else:
        config_filename = get_default_home_filename()

    logger.info('Getting configuration from {}'.format(config_filename))

    return config_filename


def default_config(config_data=None, config_overwrite={}):
    """
    First checks .pywren_config
    then checks PYWREN_CONFIG_FILE environment variable
    then ~/.pywren_config
    """
    logger.info('PyWren v{}'.format(__version__))
    logger.debug("Loading configuration")

    if not config_data:
        if 'PYWREN_CONFIG' in os.environ:
            config_data = json.loads(os.environ.get('PYWREN_CONFIG'))
        else:
            config_filename = get_default_config_filename()
            if config_filename is None:
                raise ValueError("could not find configuration file")
            config_data = load_yaml_config(config_filename)

    if 'pywren' not in config_data:
        raise Exception("pywren section is mandatory in configuration")

    # overwrite values provided by the user
    config_data['pywren'].update(config_overwrite)

    if 'storage_bucket' not in config_data['pywren']:
        raise Exception("storage_bucket is mandatory in pywren section of the configuration")

    if 'compute_backend' not in config_data['pywren']:
        config_data['pywren']['compute_backend'] = COMPUTE_BACKEND_DEFAULT
    if 'storage_backend' not in config_data['pywren']:
        config_data['pywren']['storage_backend'] = STORAGE_BACKEND_DEFAULT

    if 'rabbitmq' in config_data:
        if config_data['rabbitmq'] is None \
           or 'amqp_url' not in config_data['rabbitmq'] \
           or config_data['rabbitmq']['amqp_url'] is None:
            del config_data['rabbitmq']

    cb = config_data['pywren']['compute_backend']
    logger.debug("Loading Compute backend module: {}".format(cb))
    cb_config = importlib.import_module('pywren_ibm_cloud.compute.backends.{}.config'.format(cb))
    cb_config.load_config(config_data)

    sb = config_data['pywren']['storage_backend']
    logger.debug("Loading Storage backend module: {}".format(sb))
    sb_config = importlib.import_module('pywren_ibm_cloud.storage.backends.{}.config'.format(sb))
    sb_config.load_config(config_data)

    return config_data


def extract_storage_config(config):
    storage_config = dict()
    sb = config['pywren']['storage_backend']
    storage_config['backend'] = sb
    storage_config['bucket'] = config['pywren']['storage_bucket']

    storage_config[sb] = config[sb]
    storage_config[sb]['user_agent'] = 'pywren-ibm-cloud/{}'.format(__version__)
    if 'storage_backend_region' in config['pywren']:
        storage_config[sb]['region'] = config['pywren']['storage_backend_region']

    return storage_config


def extract_compute_config(config):
    compute_config = dict()
    cb = config['pywren']['compute_backend']
    compute_config['backend'] = cb

    compute_config[cb] = config[cb]
    compute_config[cb]['user_agent'] = 'pywren-ibm-cloud/{}'.format(__version__)
    if 'compute_backend_region' in config['pywren']:
        compute_config[cb]['region'] = config['pywren']['compute_backend_region']

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
