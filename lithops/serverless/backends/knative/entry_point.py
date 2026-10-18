#
# (C) Copyright IBM Corp. 2019
# (C) Copyright Cloudlab URV 2020
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
import uuid
import flask
import logging
from lithops.version import __version__
from lithops.utils import setup_lithops_logger
from lithops.worker import function_handler
from lithops.worker import function_invoker
from lithops.worker.utils import get_runtime_metadata

logger = logging.getLogger('lithops.worker')


proxy = flask.Flask(__name__)


@proxy.route('/', methods=['POST'])
def run():
    """
    Runs the calls of the payload, or the remote invoker, and answers once
    they finish: the open request is what keeps Knative from scaling this
    container down while it works
    """
    message = flask.request.get_json(force=True, silent=True)
    if not isinstance(message, dict):
        return flask.jsonify({'error': 'The request body must be a JSON object'}), 400

    act_id = uuid.uuid4().hex
    os.environ['__LITHOPS_ACTIVATION_ID'] = act_id
    os.environ['__LITHOPS_BACKEND'] = 'Knative'

    setup_lithops_logger(message.get('log_level', logging.INFO))

    if 'remote_invoker' in message:
        logger.info(f"Lithops v{__version__} - Starting Knative invoker")
        function_invoker(message)
    else:
        logger.info(f"Lithops v{__version__} - Starting Knative execution")
        function_handler(message)

    return flask.jsonify({'activationId': act_id}), 202


@proxy.route('/metadata', methods=['GET', 'POST'])
def preinstalls_task():
    setup_lithops_logger(logging.INFO)
    logger.info(f"Lithops v{__version__} - Generating metadata")
    runtime_meta = get_runtime_metadata()
    logger.info("Done!")
    return flask.jsonify(runtime_meta), 200


def main():
    port = int(os.getenv('PORT', 8080))
    proxy.run(host='0.0.0.0', port=port)


if __name__ == '__main__':
    main()
