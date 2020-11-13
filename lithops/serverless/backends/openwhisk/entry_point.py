#
# (C) Copyright IBM Corp. 2018
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
import sys
import logging
from lithops.version import __version__
from lithops.utils import setup_logger
from lithops.worker import function_handler
from lithops.worker import function_invoker
from lithops.constants import LOGGER_FORMAT_SHORT

logger = logging.getLogger('lithops.worker')


def main(args):
    os.environ['__LITHOPS_ACTIVATION_ID'] = os.environ['__OW_ACTIVATION_ID']

    setup_logger(args['log_level'], sys.stdout, LOGGER_FORMAT_SHORT)

    if 'remote_invoker' in args:
        logger.info("Lithops v{} - Starting OpenWhisk Functions invoker".format(__version__))
        function_invoker(args)
    else:
        logger.info("Lithops v{} - Starting OpenWhisk Functions execution".format(__version__))
        function_handler(args)

    return {"Execution": "Finished"}
