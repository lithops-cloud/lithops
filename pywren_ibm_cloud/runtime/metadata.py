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
from pywren_ibm_cloud.utils import version_str
from pywren_ibm_cloud.runtime import clone_runtime

logger = logging.getLogger(__name__)


def get_runtime_preinstalls(internal_storage, runtime, memory):
    """
    Download runtime information from storage at deserialize
    """
    log_level = os.getenv('PYWREN_LOG_LEVEL')
    logger.debug("Downloading runtime pre-installed modules from COS")
    try:
        runtime_meta = internal_storage.get_runtime_info('{}_{}'.format(runtime, memory))
        preinstalls = runtime_meta['preinstalls']
        if not log_level:
            print()
    except Exception:
        log_msg = 'Runtime {}_{} is not yet installed'.format(runtime, memory)
        logger.debug(log_msg)
        if not log_level:
            print('(Installing...)')
            old_stdout = sys.stdout
            sys.stdout = open(os.devnull, 'w')
        clone_runtime(runtime, memory=memory)
        if not log_level:
            sys.stdout = old_stdout
        runtime_meta = internal_storage.get_runtime_info('{}_{}'.format(runtime, memory))
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
