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
from lithops.serverless import ServerlessHandler
from lithops.invokers import JobMonitor
from lithops.storage import InternalStorage
from lithops.version import __version__
from concurrent.futures import ThreadPoolExecutor
from lithops.config import extract_serverless_config, extract_storage_config

logging.getLogger('pika').setLevel(logging.CRITICAL)
logger = logging.getLogger('invoker')


def function_invoker(event):
    if __version__ != event['lithops_version']:
        raise Exception("WRONGVERSION", "Lithops version mismatch",
                        __version__, event['lithops_version'])

    log_level = logging.getLevelName(logger.getEffectiveLevel())
    custom_env = {'LITHOPS_WORKER': 'True',
                  'PYTHONUNBUFFERED': 'True'}
    os.environ.update(custom_env)
    config = event['config']
    num_invokers = event['invokers']
    invoker = ServerlessInvoker(config, num_invokers, log_level)
    invoker.run(event['job_description'])


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

    def _invoke(self, job, call_id):
        """
        Method used to perform the actual invocation against the Compute Backend
        """
        payload = {'config': self.config,
                   'log_level': self.log_level,
                   'func_key': job.func_key,
                   'data_key': job.data_key,
                   'extra_env': job.extra_env,
                   'execution_timeout': job.execution_timeout,
                   'data_byte_range': job.data_ranges[int(call_id)],
                   'executor_id': job.executor_id,
                   'job_id': job.job_id,
                   'call_id': call_id,
                   'host_submit_tstamp': time.time(),
                   'lithops_version': __version__,
                   'runtime_name': job.runtime_name,
                   'runtime_memory': job.runtime_memory}

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

    def run(self, job_description):
        """
        Run a job described in job_description
        """
        job = SimpleNamespace(**job_description)

        log_msg = ('ExecutorID {} | JobID {} - Starting function '
                   'invocation: {}()  - Total: {} activations'.
                   format(job.executor_id, job.job_id,
                          job.function_name, job.total_calls))
        logger.info(log_msg)

        self.total_calls = job.total_calls

        if self.num_invokers == 0:
            # Localhost execution using processes
            for i in range(job.total_calls):
                call_id = "{:05d}".format(i)
                self._invoke(job, call_id)
        else:
            for i in range(self.num_workers):
                self.token_bucket_q.put('#')

            for i in range(job.total_calls):
                call_id = "{:05d}".format(i)
                self.pending_calls_q.put((job, call_id))

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
                job, call_id = self.pending_calls_q.get()
                future = executor.submit(self._invoke, job, call_id)
                call_futures.append(future)

        logger.info('Invoker process {} finished'.format(inv_id))
