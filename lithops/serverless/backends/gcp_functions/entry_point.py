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
from lithops.utils import setup_lithops_logger
from lithops.worker import function_handler
from lithops.worker import function_invoker
from lithops.worker.utils import get_runtime_metadata
from lithops.storage.storage import InternalStorage
from lithops.constants import JOBS_PREFIX

logger = logging.getLogger('lithops.worker')


def main(event, context):
    # pub/sub event data is b64 encoded
    args = json.loads(base64.b64decode(event['data']).decode('utf-8'))

    setup_lithops_logger(args.get('log_level', 'INFO'))

    os.environ['__LITHOPS_ACTIVATION_ID'] = uuid.uuid4().hex
    os.environ['__LITHOPS_BACKEND'] = 'Google Cloud Functions'

    if 'get_metadata' in args:
        logger.info(f"Lithops v{__version__} - Generating metadata")
        internal_storage = InternalStorage(args['get_metadata']['storage_config'])
        object_key = '/'.join([JOBS_PREFIX, args['get_metadata']['runtime_name'] + '.meta'])
        logger.info(f"Runtime metadata key {object_key}")
        runtime_meta = get_runtime_metadata()
        runtime_meta_json = json.dumps(runtime_meta)
        internal_storage.put_data(object_key, runtime_meta_json)
    elif 'remote_invoker' in args:
        logger.info(f"Lithops v{__version__} - Starting Google Cloud Functions invoker")
        function_invoker(args)
    else:
        logger.info(f"Lithops v{__version__} - Starting Google Cloud Functions execution")
        function_handler(args)

    return {"Execution": "Finished"}
