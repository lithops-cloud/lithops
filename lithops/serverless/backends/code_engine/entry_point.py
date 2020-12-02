#
# (C) Copyright IBM Corp. 2020
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
import sys
import json
import flask
import logging
from lithops.version import __version__
from lithops.utils import setup_logger, b64str_to_dict
from lithops.worker import function_handler
from lithops.worker import function_invoker
from lithops.worker.utils import get_runtime_preinstalls
from lithops.constants import JOBS_PREFIX
from lithops.storage.storage import InternalStorage


proxy = flask.Flask(__name__)

logger = logging.getLogger('lithops.worker')


@proxy.route('/', methods=['POST'])
def run():
    def error():
        response = flask.jsonify({'error': 'The action did not receive a dictionary as an argument.'})
        response.status_code = 404
        return complete(response)

    message = flask.request.get_json(force=True, silent=True)
    if message and not isinstance(message, dict):
        return error()

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    os.environ['__LITHOPS_ACTIVATION_ID'] = act_id

    setup_logger(message['log_level'])

    if 'remote_invoker' in message:
        logger.info("Lithops v{} - Starting Knative invoker".format(__version__))
        function_invoker(message)
    else:
        logger.info("Lithops v{} - Starting Knative execution".format(__version__))
        function_handler(message)

    response = flask.jsonify({"activationId": act_id})
    response.status_code = 202

    return complete(response)


@proxy.route('/preinstalls', methods=['GET', 'POST'])
def preinstalls_task():
    setup_logger(logging.INFO)
    logger.info("Lithops v{} - Generating metadata".format(__version__))
    runtime_meta = get_runtime_preinstalls()
    response = flask.jsonify(runtime_meta)
    response.status_code = 200
    logger.info("Done!")

    return complete(response)


def complete(response):
    # Add sentinel to stdout/stderr
    sys.stdout.write('%s\n' % 'XXX_THE_END_OF_AN_ACTIVATION_XXX')
    sys.stdout.flush()

    return response


def main_request():
    port = int(os.getenv('PORT', 8080))
    proxy.run(debug=True, host='0.0.0.0', port=port)


def runtime_packages(payload):
    logger.info("Lithops v{} - Generating metadata".format(__version__))
    runtime_meta = get_runtime_preinstalls()

    internal_storage = InternalStorage(payload)
    status_key = '/'.join([JOBS_PREFIX, payload['runtime_name']+'.meta'])
    logger.info("Runtime metadata key {}".format(status_key))
    dmpd_response_status = json.dumps(runtime_meta)
    internal_storage.put_data(status_key, dmpd_response_status)


def main_job(action, encoded_payload):
    logger.info("Lithops v{} - Starting Code Engine execution".format(__version__))

    payload = b64str_to_dict(encoded_payload)

    setup_logger(payload['log_level'])

    if (action == 'preinstalls'):
        runtime_packages(payload)
        return {"Execution": "Finished"}

    job_index = os.environ['JOB_INDEX']
    payload['JOB_INDEX'] = job_index
    logger.info("Action {}. Job Index {}".format(action, job_index))

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    os.environ['__LITHOPS_ACTIVATION_ID'] = act_id

    payload['data_byte_range'] = payload['data_byte_range'][int(job_index)]
    payload['call_id'] = "{:05d}".format(int(job_index))

    function_handler(payload)

    return {"Execution": "Finished"}


if __name__ == '__main__':
    if 'JOB_INDEX' in os.environ:
        main_job(sys.argv[1:][0], sys.argv[1:][1])
    else:
        main_request()
