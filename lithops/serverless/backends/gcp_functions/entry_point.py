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

import logging
import json
import base64
import os
import uuid
from lithops.version import __version__
from lithops.config import cloud_logging_config
from lithops.worker import function_handler
from lithops.worker import function_invoker

cloud_logging_config(logging.INFO)
logger = logging.getLogger('__main__')


def main(event, context):
    logger.info("Starting GCP Functions function execution")
    args = json.loads(base64.b64decode(event['data']).decode('utf-8'))
    os.environ['__PW_ACTIVATION_ID'] = uuid.uuid4().hex
    if 'remote_invoker' in args:
        logger.info("Lithops v{} - Starting invoker".format(__version__))
        function_invoker(args)
    else:
        logger.info("Lithops v{} - Starting execution".format(__version__))
        function_handler(args)

    return {"Execution": "Finished"}
