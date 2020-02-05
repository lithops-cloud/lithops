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
import random
from types import SimpleNamespace
from multiprocessing import Process, Queue
from pywren_ibm_cloud.compute import Compute
from pywren_ibm_cloud.invoker import JobMonitor
from pywren_ibm_cloud.storage import InternalStorage
from pywren_ibm_cloud.version import __version__
from concurrent.futures import ThreadPoolExecutor
from pywren_ibm_cloud.config import cloud_logging_config, extract_compute_config, extract_storage_config

logging.getLogger('pika').setLevel(logging.CRITICAL)
logger = logging.getLogger('invoker')


def function_invoker(event):
    if __version__ != event['pywren_version']:
        raise Exception("WRONGVERSION", "PyWren version mismatch",
                        __version__, event['pywren_version'])

    log_level = event['log_level']
    cloud_logging_config(log_level)
    log_level = logging.getLevelName(logger.getEffectiveLevel())
    custom_env = {'PYWREN_FUNCTION': 'True',
                  'PYTHONUNBUFFERED': 'True',
                  'PYWREN_LOGLEVEL': log_level}
    os.environ.update(custom_env)
    config = event['config']
    invoker = FunctionInvoker(config, log_level)
    invoker.run(event['job_description'])


class FunctionInvoker:
    """
    Module responsible to perform the invocations against the compute backend
    """

    def __init__(self, config, log_level):
        self.config = config
        self.log_level = log_level
        storage_config = extract_storage_config(self.config)
        self.internal_storage = InternalStorage(storage_config)
        compute_config = extract_compute_config(self.config)

        self.remote_invoker = self.config['pywren'].get('remote_invoker', False)
        self.rabbitmq_monitor = self.config['pywren'].get('rabbitmq_monitor', False)
        if self.rabbitmq_monitor:
            self.rabbit_amqp_url = self.config['rabbitmq'].get('amqp_url')

        self.workers = self.config['pywren'].get('workers')
        logger.debug('Total workers: {}'.format(self.workers))

        self.compute_handlers = []
        cb = compute_config['backend']
        regions = compute_config[cb].get('region')
        if regions and type(regions) == list:
            for region in regions:
                new_compute_config = compute_config.copy()
                new_compute_config[cb]['region'] = region
                self.compute_handlers.append(Compute(new_compute_config))
        else:
            self.compute_handlers.append(Compute(compute_config))

        self.token_bucket_q = Queue()
        self.pending_calls_q = Queue()

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
                   'host_submit_time': time.time(),
                   'pywren_version': __version__,
                   'runtime_name': job.runtime_name,
                   'runtime_memory': job.runtime_memory}

        # do the invocation
        start = time.time()
        compute_handler = random.choice(self.compute_handlers)
        activation_id = compute_handler.invoke(job.runtime_name, job.runtime_memory, payload)
        roundtrip = time.time() - start
        resp_time = format(round(roundtrip, 3), '.3f')

        if not activation_id:
            self.pending_calls_q.put((job, call_id))
            return

        logger.info('ExecutorID {} | JobID {} - Function invocation {} done! ({}s) - Activation'
                    ' ID: {}'.format(job.executor_id, job.job_id, call_id, resp_time, activation_id))

        return call_id

    def run(self, job_description):
        """
        Run a job described in job_description
        """
        job = SimpleNamespace(**job_description)

        log_msg = ('ExecutorID {} | JobID {} - Starting function invocation: {}()  - Total: {} '
                   'activations'.format(job.executor_id, job.job_id, job.function_name, job.total_calls))
        logger.info(log_msg)

        self.total_calls = job.total_calls

        for i in range(self.workers):
            self.token_bucket_q.put('#')

        for i in range(job.total_calls):
            call_id = "{:05d}".format(i)
            self.pending_calls_q.put((job, call_id))

        self.job_monitor.start_job_monitoring(job)

        invokers = []
        for inv_id in range(4):
            p = Process(target=self._run_process, args=(inv_id, ))
            invokers.append(p)
            p.daemon = True
            p.start()

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
