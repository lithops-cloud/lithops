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
import logging
import json

from lithops.storage import InternalStorage
from lithops.version import __version__
from lithops.utils import setup_lithops_logger
from lithops.worker import function_handler
from lithops.worker import function_invoker
from lithops.worker.utils import get_runtime_preinstalls

logger = logging.getLogger('lithops.worker')

if __name__ == '__main__':
    print(os.environ)
    action = os.getenv('LITHOPS_ACTION')

    os.environ['__LITHOPS_BACKEND'] = 'AWS Batch'

    if action == 'get_preinstalls':
        lithops_conf_json = os.environ['__LITHOPS_CONFIG']
        lithops_conf = json.loads(lithops_conf_json)
        setup_lithops_logger(lithops_conf.get('log_level', logging.INFO))
        logger.info("Lithops v{} - Generating metadata".format(__version__))
        runtime_meta = get_runtime_preinstalls()
        internal_storage = InternalStorage(lithops_conf)
        status_key = lithops_conf['runtime_name'] + '.meta'
        logger.info("Runtime metadata key {}".format(status_key))
        runtime_meta_json = json.dumps(runtime_meta)
        internal_storage.put_data(status_key, runtime_meta_json)
    elif action == 'remote_invoker':
        lithops_payload_json = os.environ['__LITHOPS_PAYLOAD']
        lithops_payload = json.loads(lithops_payload_json)
        logger.info("Lithops v{} - Starting AWS Lambda invoker".format(__version__))
        function_invoker(lithops_payload)
    else:
        print(action)
        lithops_payload_json = os.environ['__LITHOPS_PAYLOAD']
        lithops_payload = json.loads(lithops_payload_json)
        logger.info("Lithops v{} - Starting AWS Lambda execution".format(__version__))
        function_handler(lithops_payload)
