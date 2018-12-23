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
import logging
from pywren_ibm_cloud.serialize import default_preinstalls

logger = logging.getLogger(__name__)


def get_runtime_preinstalls(internal_storage, runtime):
    """
    Download runtime information from storage at deserialize
    """
    if runtime in default_preinstalls.modules:
        logger.debug("Using serialize/default_preinstalls")
        runtime_meta = default_preinstalls.modules[runtime]
        preinstalls = runtime_meta['preinstalls']
    else:
        logger.debug("Downloading runtime pre-installed modules from COS")
        runtime_meta = internal_storage.get_runtime_info(runtime)
        preinstalls = runtime_meta['preinstalls']

    if not runtime_valid(runtime_meta):
        raise Exception(("The indicated runtime: {} "
                         "is not appropriate for this Python version.")
                        .format(runtime))

    return preinstalls


def version_str(version_info):
    return "{}.{}".format(version_info[0], version_info[1])


def runtime_valid(runtime_meta):
    """
    Basic checks
    """
    logger.debug("Verifying Python versions")
    this_version_str = version_str(sys.version_info)
    return this_version_str == runtime_meta['python_ver']
