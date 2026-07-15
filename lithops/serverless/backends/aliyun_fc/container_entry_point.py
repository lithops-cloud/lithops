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
# HTTP entry point for Aliyun FC custom-container runtimes.
# See: https://www.alibabacloud.com/help/en/functioncompute/fc/user-guide/custom-container/

import json
import os
import logging

from flask import Flask, request

from lithops.version import __version__
from lithops.utils import setup_lithops_logger
from lithops.worker import function_handler
from lithops.worker import function_invoker
from lithops.worker.utils import get_runtime_metadata

logger = logging.getLogger('lithops.worker')

app = Flask(__name__)


@app.route('/initialize', methods=['POST'])
def initialize():
    request_id = request.headers.get('x-fc-request-id', '')
    logger.info('FC Initialize Start RequestId: %s', request_id)
    logger.info('FC Initialize End RequestId: %s', request_id)
    return f'Function is initialized, request_id: {request_id}\n'


@app.route('/invoke', methods=['POST'])
def invoke():
    request_id = request.headers.get('x-fc-request-id', '')
    os.environ['__LITHOPS_ACTIVATION_ID'] = request_id
    os.environ['__LITHOPS_BACKEND'] = 'Aliyun Function Compute'

    raw = request.get_data()
    if not raw:
        return 'Empty event\n', 400

    args = json.loads(raw.decode('utf-8') if isinstance(raw, bytes) else raw)
    setup_lithops_logger(args.get('log_level', logging.INFO))

    if args.get('get_metadata'):
        logger.info('Lithops v%s - Generating metadata', __version__)
        return json.dumps(get_runtime_metadata()), 200, {'Content-Type': 'application/json'}

    if 'remote_invoker' in args:
        logger.info('Lithops v%s - Starting Aliyun Function Compute invoker', __version__)
        function_invoker(args)
    else:
        logger.info('Lithops v%s - Starting Aliyun Function Compute execution', __version__)
        function_handler(args)

    return json.dumps({'Execution': 'Finished'}), 200, {'Content-Type': 'application/json'}


if __name__ == '__main__':
    port = int(os.getenv('CAPort', '9000'))
    app.run(host='0.0.0.0', port=port)
