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
import pika
import time
import logging
import random
from threading import Thread
from types import SimpleNamespace
from multiprocessing import Process, Queue
from pywren_ibm_cloud.compute import Compute
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
                   'pywren_version': __version__}

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
                   'activations'.format(job.executor_id, job.job_id, job.func_name, job.total_calls))
        logger.info(log_msg)

        self.total_calls = job.total_calls

        for i in range(self.workers):
            self.token_bucket_q.put('#')

        for i in range(job.total_calls):
            call_id = "{:05d}".format(i)
            self.pending_calls_q.put((job, call_id))
        self._start_job_status_checker(job)

        invokers = []
        for i in range(4):
            p = Process(target=self.run_process, args=())
            invokers.append(p)
            p.daemon = True
            p.start()

        for p in invokers:
            p.join()

    def _start_job_status_checker(self, job):
        if self.rabbitmq_monitor:
            th = Thread(target=self._job_status_checker_worker_rabbitmq, args=(job,))
        else:
            th = Thread(target=self._job_status_checker_worker_os, args=(job,))
        th.daemon = True
        th.start()

    def _job_status_checker_worker_os(self, job):
        logger.debug('ExecutorID {} | JobID {} - Starting job status checker worker'.format(job.executor_id, job.job_id))
        total_callids_done_in_job = 0
        time.sleep(1)

        while total_callids_done_in_job < job.total_calls:
            callids_done_in_job = set(self.internal_storage.get_job_status(job.executor_id, job.job_id))
            total_new_tokens = len(callids_done_in_job) - total_callids_done_in_job
            total_callids_done_in_job = total_callids_done_in_job + total_new_tokens
            for i in range(total_new_tokens):
                self.token_bucket_q.put('#')
            time.sleep(0.1)

    def _job_status_checker_worker_rabbitmq(self, job):
        logger.debug('ExecutorID {} | JobID {} - Starting job status checker worker'.format(job.executor_id, job.job_id))
        total_callids_done_in_job = 0

        exchange = 'pywren-{}-{}'.format(job.executor_id, job.job_id)
        queue_0 = '{}-0'.format(exchange)  # For waiting
        queue_1 = '{}-1'.format(exchange)  # For invoker

        params = pika.URLParameters(self.rabbit_amqp_url)
        connection = pika.BlockingConnection(params)
        channel = connection.channel()
        channel.exchange_declare(exchange=exchange, exchange_type='fanout', auto_delete=True)
        channel.queue_declare(queue=queue_0, auto_delete=True)
        channel.queue_bind(exchange=exchange, queue=queue_0)
        channel.queue_declare(queue=queue_1, exclusive=True)
        channel.queue_bind(exchange=exchange, queue=queue_1)

        def callback(ch, method, properties, body):
            nonlocal total_callids_done_in_job
            self.token_bucket_q.put('#')
            #self.q.put(body.decode("utf-8"))
            total_callids_done_in_job += 1
            if total_callids_done_in_job == job.total_calls:
                ch.stop_consuming()
                ch.exchange_delete(exchange)

        channel.basic_consume(callback, queue=queue_1, no_ack=True)
        channel.start_consuming()

    def run_process(self):
        """
        Run process that implements token bucket scheduling approach
        """
        logger.info('Invoker process started')
        call_futures = []
        with ThreadPoolExecutor(max_workers=250) as executor:
            while self.pending_calls_q.qsize() > 0:
                self.token_bucket_q.get()
                job, call_id = self.pending_calls_q.get()
                future = executor.submit(self._invoke, job, call_id)
                call_futures.append(future)
                # THERE IS A BUG SINCE CALL_FUTRES MIGHT BE ERROR

        logger.info('Invoker process finished')
