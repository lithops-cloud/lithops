#
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
import logging
import azure.functions as func
from lithops.version import __version__
from lithops.utils import setup_logger
from lithops.worker import function_handler
from lithops.worker import function_invoker

logger = logging.getLogger('lithops.worker')


def main(msgIn: func.QueueMessage):
    try:
        args = json.loads(msgIn.get_body())
    except Exception:
        args = msgIn.get_json()

    os.environ['__PW_ACTIVATION_ID'] = str(msgIn.id)
    setup_logger(args['log_level'])
    if 'remote_invoker' in args:
        logger.info("Lithops v{} - Starting invoker".format(__version__))
        function_invoker(args)
    else:
        logger.info("Lithops v{} - Starting execution".format(__version__))
        function_handler(args)

    return {"Execution": "Finished"}
