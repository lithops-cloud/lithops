#
# (C) Copyright IBM Corp. 2019
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
import time
import logging
import multiprocessing as mp
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

from lithops.serverless import ServerlessHandler
from lithops.invokers import JobMonitor
from lithops.storage import InternalStorage
from lithops.version import __version__
from lithops.utils import iterchunks
from lithops.config import extract_serverless_config, extract_storage_config


logger = logging.getLogger(__name__)


def function_invoker(job_payload):
    if __version__ != job_payload['lithops_version']:
        raise Exception("WRONGVERSION", "Lithops version mismatch",
                        __version__, job_payload['lithops_version'])

    log_level = logging.getLevelName(logger.getEffectiveLevel())
    custom_env = {'LITHOPS_WORKER': 'True',
                  'PYTHONUNBUFFERED': 'True'}
    os.environ.update(custom_env)
    config = job_payload['config']
    num_invokers = job_payload['invokers']
    invoker = ServerlessInvoker(config, num_invokers, log_level)
    invoker.run(job_payload)


class ServerlessInvoker:
    """
    Module responsible to perform the invocations against the serverless compute backend
    """

    def __init__(self, config, num_invokers, log_level):
        self.config = config
        self.num_invokers = num_invokers
        self.log_level = log_level
        storage_config = extract_storage_config(self.config)
        self.internal_storage = InternalStorage(storage_config)

        self.remote_invoker = self.config['lithops'].get('remote_invoker', False)
        self.rabbitmq_monitor = self.config['lithops'].get('rabbitmq_monitor', False)
        if self.rabbitmq_monitor:
            self.rabbit_amqp_url = self.config['rabbitmq'].get('amqp_url')

        self.num_workers = self.config['lithops'].get('workers')
        logger.info('Total workers: {}'.format(self.num_workers))

        serverless_config = extract_serverless_config(self.config)
        self.serverless_handler = ServerlessHandler(serverless_config, storage_config)

        self.token_bucket_q = mp.Queue()
        self.pending_calls_q = mp.Queue()

        self.job_monitor = JobMonitor(self.config, self.internal_storage, self.token_bucket_q)

    def _invoke(self, job, call_ids_range):
        """
        Method used to perform the actual invocation against the Compute Backend
        """
        data_byte_ranges = [job.data_byte_ranges[int(call_id)] for call_id in call_ids_range]
        payload = {'config': self.config,
                   'chunksize': job.chunksize,
                   'log_level': self.log_level,
                   'func_key': job.func_key,
                   'data_key': job.data_key,
                   'extra_env': job.extra_env,
                   'execution_timeout': job.execution_timeout,
                   'data_byte_ranges': data_byte_ranges,
                   'executor_id': job.executor_id,
                   'job_id': job.job_id,
                   'job_key': job.job_key,
                   'call_ids': call_ids_range,
                   'host_submit_tstamp': time.time(),
                   'lithops_version': __version__,
                   'runtime_name': job.runtime_name,
                   'runtime_memory': job.runtime_memory,
                   'worker_processes': job.worker_processes}

        # do the invocation
        start = time.time()
        activation_id = self.serverless_handler.invoke(job.runtime_name,
                                                       job.runtime_memory,
                                                       payload)
        roundtrip = time.time() - start
        resp_time = format(round(roundtrip, 3), '.3f')

        if not activation_id:
            self.pending_calls_q.put((job, call_id))
            return

        logger.info('ExecutorID {} | JobID {} - Function invocation '
                    '{} done! ({}s) - Activation  ID: {}'.
                    format(job.executor_id, job.job_id, call_id,
                           resp_time, activation_id))

        return call_id

    def run(self, job_payload):
        """
        Run a job described in job_description
        """
        job = SimpleNamespace(**job_payload)

        job.total_calls = len(job.call_ids)

        logger.info('ExecutorID {} | JobID {} - Starting function '
                    'invocation - Total: {} activations'
                    .format(job.executor_id, job.job_id, job.total_calls))

        logger.info('ExecutorID {} | JobID {} - Chunksize:'
                    ' {} - Worker processes: {}'
                    .format(job.executor_id, job.job_id,
                            job.chunksize, job.worker_processes))

        for i in range(self.num_workers):
            self.token_bucket_q.put('#')

        for call_ids_range in iterchunks(job.call_ids, job.chunksize):
            self.pending_calls_q.put((job, call_ids_range))

        self.job_monitor.start_job_monitoring(job)

        invokers = []
        for inv_id in range(self.num_invokers):
            p = mp.Process(target=self._run_process, args=(inv_id, ))
            p.daemon = True
            p.start()
            invokers.append(p)

        for p in invokers:
            p.join()

    def _run_process(self, inv_id):
        """
        Run process that implements token bucket scheduling approach
        """
        logger.info('Invoker process {} started'.format(inv_id))
        call_futures = []
        with ThreadPoolExecutor(max_workers=250) as executor:
            # TODO: Change pending_calls_q check
            while self.pending_calls_q.qsize() > 0:
                self.token_bucket_q.get()
                job, call_ids_range = self.pending_calls_q.get()
                future = executor.submit(self._invoke, job, call_ids_range)
                call_futures.append(future)

        logger.info('Invoker process {} finished'.format(inv_id))
