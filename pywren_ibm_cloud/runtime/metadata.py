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

import sys
import os
import logging
from pywren_ibm_cloud.utils import version_str, create_runtime_name
from pywren_ibm_cloud.runtime import create_runtime

logger = logging.getLogger(__name__)


def get_runtime_preinstalls(internal_storage, runtime, memory, config):
    """
    Download runtime information from storage at deserialize
    """
    log_level = os.getenv('PYWREN_LOG_LEVEL')
    try:
        logger.debug("Downloading runtime pre-installed modules from COS")
        region = config['ibm_cf']['endpoint'].split('//')[1].split('.')[0]
        namespace = config['ibm_cf']['namespace']
        runtime_name = create_runtime_name(runtime, memory)
        runtime_meta = internal_storage.get_runtime_info(region, namespace, runtime_name)
        preinstalls = runtime_meta['preinstalls']
        if not log_level:
            print()
    except Exception:
        logger.debug('Runtime {} is not yet installed'.format(runtime_name))
        if not log_level:
            print('(Installing...)')
        create_runtime(runtime, memory=memory, config=config)
        runtime_meta = internal_storage.get_runtime_info(region, namespace, runtime_name)
        preinstalls = runtime_meta['preinstalls']

    if not runtime_valid(runtime_meta):
        raise Exception(("The indicated runtime: {} "
                         "is not appropriate for this Python version.")
                        .format(runtime))

    return preinstalls


def runtime_valid(runtime_meta):
    """
    Basic checks
    """
    logger.debug("Verifying Python versions")
    this_version_str = version_str(sys.version_info)
    return this_version_str == runtime_meta['python_ver']
