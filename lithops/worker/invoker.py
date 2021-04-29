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
import logging
import multiprocessing as mp
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

from lithops.serverless import ServerlessHandler
from lithops.monitor import JobMonitor
from lithops.storage import InternalStorage
from lithops.utils import iterchunks
from lithops.config import extract_serverless_config, extract_storage_config
from lithops.invokers import FaaSInvoker, create_invoker


logger = logging.getLogger(__name__)


def function_invoker(job_payload):
    """
    Method used as a remote invoker
    """
    config = job_payload['config']
    job = SimpleNamespace(**job_payload['job'])

    env = {'LITHOPS_WORKER': 'True', 'PYTHONUNBUFFERED': 'True',
           '__LITHOPS_SESSION_ID': job.job_key}
    os.environ.update(env)

    # Create the monitoring system
    monitoring_backend = config['lithops']['monitoring'].lower()
    monitoring_config = config.get(monitoring_backend)
    job_monitor = JobMonitor(monitoring_backend, monitoring_config)

    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)

    serverless_config = extract_serverless_config(config)
    compute_handler = ServerlessHandler(serverless_config, storage_config)

    # Create the invokder
    #invoker = FaaSRemoteInvoker(config, job.executor_id, internal_storage, compute_handler, job_monitor)
    invoker = create_invoker(config, job.executor_id, internal_storage, compute_handler, job_monitor)
    invoker.run_job(job)


class FaaSRemoteInvoker(FaaSInvoker):
    """
    Module responsible to perform the invocations against the serverless compute backend
    """
    ASYNC_INVOKERS = 2

    def __init__(self, config, executor_id, internal_storage, compute_handler, job_monitor):
        super().__init__(config, executor_id, internal_storage, compute_handler, job_monitor)

        self.job_monitor.token_bucket_q = mp.Queue()
        self.pending_calls_q = mp.Queue()

    def _invoker_process(self, inv_id):
        """
        Run process that implements token bucket scheduling approach
        """
        logger.info('Invoker process {} started'.format(inv_id))
        with ThreadPoolExecutor(max_workers=250) as executor:
            # TODO: Change pending_calls_q check
            while self.pending_calls_q.qsize() > 0:
                self.job_monitor.token_bucket_q.get()
                job, call_ids_range = self.pending_calls_q.get()
                executor.submit(self._invoke_task, job, call_ids_range)

        logger.info('Invoker process {} finished'.format(inv_id))

    def _invoke_job(self, job):
        """
        Run a job described in job_description
        """
        for i in range(self.workers):
            self.job_monitor.token_bucket_q.put('#')

        for call_ids_range in iterchunks(range(job.total_calls), job.chunksize):
            self.pending_calls_q.put((job, call_ids_range))

        invokers = []
        for inv_id in range(self.ASYNC_INVOKERS):
            p = mp.Process(target=self._invoker_process, args=(inv_id, ))
            p.daemon = True
            p.start()
            invokers.append(p)

        for p in invokers:
            p.join()
