#
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
import sys
import uuid
import json
import logging
import flask
import requests
from functools import partial

from lithops.version import __version__
from lithops.utils import setup_lithops_logger, b64str_to_dict,\
    iterchunks
from lithops.worker import function_handler
from lithops.worker.utils import get_runtime_preinstalls
from lithops.constants import JOBS_PREFIX
from lithops.storage.storage import InternalStorage


logger = logging.getLogger('lithops.worker')

proxy = flask.Flask(__name__)

IDGIVER_PORT = 8080

JOB_INDEXES = {}


@proxy.route('/getid/<jobkey>', methods=['GET'])
def get_id(jobkey):
    global JOB_INDEXES

    if jobkey not in JOB_INDEXES:
        JOB_INDEXES[jobkey] = 0
    else:
        JOB_INDEXES[jobkey] += 1

    return str(JOB_INDEXES[jobkey])


def id_giver():
    proxy.run(debug=True, host='0.0.0.0', port=IDGIVER_PORT)


def extract_runtime_meta(encoded_payload):
    logger.info("Lithops v{} - Generating metadata".format(__version__))

    payload = b64str_to_dict(encoded_payload)

    setup_lithops_logger(payload['log_level'])

    runtime_meta = get_runtime_preinstalls()

    internal_storage = InternalStorage(payload)
    status_key = '/'.join([JOBS_PREFIX, payload['runtime_name']+'.meta'])
    logger.info("Runtime metadata key {}".format(status_key))
    dmpd_response_status = json.dumps(runtime_meta)
    internal_storage.put_data(status_key, dmpd_response_status)


def run_job(encoded_payload):
    logger.info("Lithops v{} - Starting kubernetes execution".format(__version__))

    payload = b64str_to_dict(encoded_payload)
    setup_lithops_logger(payload['log_level'])

    job_key = payload['job_key']
    idgiver_ip = os.environ['IDGIVER_POD_IP']
    res = requests.get('http://{}:{}/getid/{}'.format(idgiver_ip, IDGIVER_PORT, job_key))
    job_index = int(res.text)

    act_id = str(uuid.uuid4()).replace('-', '')[:12]
    os.environ['__LITHOPS_ACTIVATION_ID'] = act_id
    logger.info("Activation ID: {} - Job Index: {}".format(act_id, job_index))

    chunksize = payload['chunksize']
    call_ids_ranges = [call_ids_range for call_ids_range in iterchunks(payload['call_ids'], chunksize)]
    call_ids = call_ids_ranges[job_index]
    data_byte_ranges = [payload['data_byte_ranges'][int(call_id)] for call_id in call_ids]

    payload['call_ids'] = call_ids
    payload['data_byte_ranges'] = data_byte_ranges

    function_handler(payload)


if __name__ == '__main__':
    action = sys.argv[1]
    encoded_payload = sys.argv[2]

    switcher = {
        'preinstalls': partial(extract_runtime_meta, encoded_payload),
        'run': partial(run_job, encoded_payload),
        'id_giver': id_giver

    }

    func = switcher.get(action, lambda: "Invalid command")
    func()
