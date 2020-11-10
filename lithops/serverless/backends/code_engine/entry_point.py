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
import json
import logging
import pkgutil
from lithops.version import __version__
from lithops.utils import setup_logger
from lithops.worker import function_handler
from lithops.storage import InternalStorage
from lithops.constants import JOBS_PREFIX
from lithops.utils import sizeof_fmt


logger = logging.getLogger('lithops.worker')


def binary_to_dict(the_binary):
    jsn = ''.join(chr(int(x, 2)) for x in the_binary.split())
    d = json.loads(jsn)
    return d


def runtime_packages(storage_config):
    logger.info("Extracting preinstalled Python modules...")
    internal_storage = InternalStorage(storage_config)

    runtime_meta = dict()
    mods = list(pkgutil.iter_modules())
    runtime_meta['preinstalls'] = [entry for entry in sorted([[mod, is_pkg] for _, mod, is_pkg in mods])]
    python_version = sys.version_info
    runtime_meta['python_ver'] = str(python_version[0])+"."+str(python_version[1])

    activation_id = storage_config['activation_id']

    status_key = '/'.join([JOBS_PREFIX, activation_id, 'runtime_metadata'])
    logger.debug("Runtime metadata key {}".format(status_key))
    dmpd_response_status = json.dumps(runtime_meta)
    drs = sizeof_fmt(len(dmpd_response_status))
    logger.info("Storing execution stats - Size: {}".format(drs))
    internal_storage.put_data(status_key, dmpd_response_status)


def main(action, payload_decoded):
    logger.info("Welcome to Lithops-Code-Engine entry point. Action {}".format(action))

    payload = binary_to_dict(payload_decoded)

    setup_logger(payload['log_level'])

    logger.info(payload)
    if (action == 'preinstals'):
        runtime_packages(payload)
        return {"Execution": "Finished"}
    job_index = os.environ['JOB_INDEX']
    logger.info("Action {}. Job Index {}".format(action, job_index))
    os.environ['__PW_ACTIVATION_ID'] = payload['activation_id']
    payload['JOB_INDEX'] = job_index
    if 'remote_invoker' in payload:
        logger.info("Lithops v{} - Remote Invoker. Starting execution".format(__version__))
        #function_invoker(payload)
        payload['data_byte_range'] = payload['job_description']['data_ranges'][int(job_index)]
        for key in payload['job_description']:
            payload[key] = payload['job_description'][key]
        payload['host_submit_tstamp'] = payload['metadata']['host_job_create_tstamp']
        payload['call_id'] = "{:05d}".format(int(job_index))

        function_handler(payload)
    else:
        logger.info("Lithops v{} - Starting execution".format(__version__))
        function_handler(payload)

    return {"Execution": "Finished"}


if __name__ == '__main__':
    main(sys.argv[1:][0], sys.argv[1:][1])
