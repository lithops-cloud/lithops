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
import time
import requests
from functools import partial

from lithops.version import __version__
from lithops.utils import setup_lithops_logger, b64str_to_dict
from lithops.worker import function_handler
from lithops.worker.utils import get_runtime_metadata
from lithops.constants import JOBS_PREFIX
from lithops.storage.storage import InternalStorage

from lithops.serverless.backends.k8s import config

logger = logging.getLogger('lithops.worker')

proxy = flask.Flask(__name__)

JOB_INDEXES = {}


@proxy.route('/get-range/<jobkey>/<total_calls>/<chunksize>', methods=['GET'])
def get_range(jobkey, total_calls, chunksize):
    global JOB_INDEXES

    range_start = 0 if jobkey not in JOB_INDEXES else JOB_INDEXES[jobkey]
    range_end = min(range_start + int(chunksize), int(total_calls))
    JOB_INDEXES[jobkey] = range_end

    range = "-1" if range_start == int(total_calls) else f'{range_start}-{range_end}'
    remote_host = flask.request.remote_addr
    proxy.logger.info(f'Sending range "{range}" to Host {remote_host}')

    return range


def run_master_server():
    # Start Redis Server in the background
    logger.info("Starting redis server in Master Pod")
    os.system("redis-server --bind 0.0.0.0 --daemonize yes")
    logger.info("Redis server started")

    proxy.logger.setLevel(logging.DEBUG)
    proxy.run(debug=True, host='0.0.0.0', port=config.MASTER_PORT, use_reloader=False)


def extract_runtime_meta(payload):
    logger.info(f"Lithops v{__version__} - Generating metadata")

    runtime_meta = get_runtime_metadata()

    internal_storage = InternalStorage(payload)
    status_key = '/'.join([JOBS_PREFIX, payload['runtime_name'] + '.meta'])
    logger.info(f"Runtime metadata key {status_key}")
    dmpd_response_status = json.dumps(runtime_meta)
    internal_storage.put_data(status_key, dmpd_response_status)


def run_job(payload):
    logger.info(f"Lithops v{__version__} - Starting kubernetes execution")

    os.environ['__LITHOPS_ACTIVATION_ID'] = str(uuid.uuid4()).replace('-', '')[:12]
    os.environ['__LITHOPS_BACKEND'] = 'k8s'

    total_calls = payload['total_calls']
    job_key = payload['job_key']
    worker_processes = payload['worker_processes']
    chunksize = payload['chunksize']

    # Optimize chunksize to the number of processess if necessary
    chunksize = worker_processes if worker_processes > chunksize else chunksize

    call_ids = payload['call_ids']
    data_byte_ranges = payload['data_byte_ranges']

    master_ip = os.environ['MASTER_POD_IP']

    job_finished = False
    while not job_finished:
        call_ids_range = None

        while call_ids_range is None:
            try:
                server = f'http://{master_ip}:{config.MASTER_PORT}'
                url = f'{server}/get-range/{job_key}/{total_calls}/{chunksize}'
                res = requests.get(url)
                call_ids_range = res.text  # for example: 0-5
            except Exception:
                time.sleep(0.1)

        logger.info(f"Received range: {call_ids_range}")
        if call_ids_range == "-1":
            job_finished = True
            continue

        start, end = map(int, call_ids_range.split('-'))
        dbr = [data_byte_ranges[int(call_id)] for call_id in call_ids[start:end]]
        payload['call_ids'] = call_ids[start:end]
        payload['data_byte_ranges'] = dbr
        function_handler(payload)

    logger.info("Finishing kubernetes execution")


if __name__ == '__main__':
    action = sys.argv[1]
    encoded_payload = sys.argv[2]

    payload = b64str_to_dict(encoded_payload)
    setup_lithops_logger(payload.get('log_level', 'INFO'))

    switcher = {
        'get_metadata': partial(extract_runtime_meta, payload),
        'run_job': partial(run_job, payload),
        'run_master': run_master_server
    }

    func = switcher.get(action, lambda: "Invalid command")
    func()
