#
# (C) Copyright PyWren Team 2018
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
import sys
import zlib
import pika
import time
import json
import queue
import base64
import pickle
import logging
import traceback
import multiprocessing as mp
from threading import Thread
from multiprocessing import Process, Pipe
from multiprocessing.managers import SyncManager
from distutils.util import strtobool
from tblib import pickling_support
from types import SimpleNamespace

from lithops.version import __version__
from lithops.config import extract_storage_config
from lithops.storage import InternalStorage
from lithops.worker.taskrunner import TaskRunner
from lithops.worker.utils import get_memory_usage, LogStream, custom_redirection,\
    get_function_and_modules, get_function_data
from lithops.constants import JOBS_PREFIX, LITHOPS_TEMP_DIR
from lithops.utils import sizeof_fmt, setup_lithops_logger, is_unix_system
from lithops.storage.utils import create_status_key, create_job_key,\
    create_init_key

pickling_support.install()

logger = logging.getLogger(__name__)


class ShutdownSentinel():
    """Put an instance of this class on the queue to shut it down"""
    pass


def function_handler(payload):
    job = SimpleNamespace(**payload)
    processes = min(job.worker_processes, len(job.call_ids))

    logger.info('Tasks received: {} - Concurrent workers: {}'
                .format(len(job.call_ids), processes))

    storage_config = extract_storage_config(job.config)
    internal_storage = InternalStorage(storage_config)
    job.func = get_function_and_modules(job, internal_storage)
    job_data = get_function_data(job, internal_storage)

    if processes == 1:
        job_queue = queue.Queue()
        for task_id in job.call_ids:
            data = job_data.pop(0)
            job_queue.put((job, task_id, data))
        job_queue.put(ShutdownSentinel())
        process_runner(job_queue, internal_storage)
    else:
        manager = SyncManager()
        manager.start()
        job_queue = manager.Queue()
        job_runners = []

        for runner_id in range(processes):
            p = mp.Process(target=process_runner, args=(job_queue, internal_storage))
            job_runners.append(p)
            p.start()
            logger.info('Worker process {} started'.format(runner_id))

        for task_id in job.call_ids:
            data = job_data.pop(0)
            job_queue.put((job, task_id, data))

        for i in range(processes):
            job_queue.put(ShutdownSentinel())

        for runner in job_runners:
            runner.join()

        manager.shutdown()


def process_runner(job_queue, internal_storage):
    """
    Listens the job_queue and executes the jobs
    """
    while True:
        event = job_queue.get(block=True)
        if isinstance(event, ShutdownSentinel):
            break

        task, task_id, data = event
        task.id = task_id
        task.data = data

        bucket = task.config['lithops']['storage_bucket']
        task.task_dir = os.path.join(LITHOPS_TEMP_DIR, bucket, JOBS_PREFIX, task.job_key, task_id)
        task.log_file = os.path.join(task.task_dir, 'execution.log')
        os.makedirs(task.task_dir, exist_ok=True)

        with open(task.log_file, 'a') as log_strem:
            task.log_stream = LogStream(log_strem)
            with custom_redirection(task.log_stream):
                run_task(task, internal_storage)


def run_task(task, internal_storage):
    """
    Runs a single job within a separate process
    """
    start_tstamp = time.time()
    setup_lithops_logger(task.log_level)

    backend = os.environ.get('__LITHOPS_BACKEND', '')
    logger.info("Lithops v{} - Starting {} execution".format(__version__, backend))
    logger.info("Execution ID: {}/{}".format(task.job_key, task.id))

    if task.runtime_memory:
        logger.debug('Runtime: {} - Memory: {}MB - Timeout: {} seconds'
                     .format(task.runtime_name, task.runtime_memory, task.execution_timeout))
    else:
        logger.debug('Runtime: {} - Timeout: {} seconds'.format(task.runtime_name, task.execution_timeout))

    env = task.extra_env
    env['LITHOPS_WORKER'] = 'True'
    env['PYTHONUNBUFFERED'] = 'True'
    env['LITHOPS_CONFIG'] = json.dumps(task.config)
    env['__LITHOPS_SESSION_ID'] = '-'.join([task.job_key, task.id])
    os.environ.update(env)

    call_status = CallStatus(task.config, internal_storage)
    call_status.response['worker_start_tstamp'] = start_tstamp
    call_status.response['host_submit_tstamp'] = task.host_submit_tstamp
    call_status.response['call_id'] = task.id
    call_status.response['job_id'] = task.job_id
    call_status.response['executor_id'] = task.executor_id

    show_memory_peak = strtobool(os.environ.get('SHOW_MEMORY_PEAK', 'False'))

    try:
        # send init status event
        call_status.send('__init__')

        if show_memory_peak:
            mm_handler_conn, mm_conn = Pipe()
            memory_monitor = Thread(target=memory_monitor_worker, args=(mm_conn, ))
            memory_monitor.start()

        task.stats_file = os.path.join(task.task_dir, 'task_stats.txt')
        handler_conn, jobrunner_conn = Pipe()
        taskrunner = TaskRunner(task, jobrunner_conn, internal_storage)
        logger.debug('Starting TaskRunner process')
        jrp = Process(target=taskrunner.run) if is_unix_system() else Thread(target=taskrunner.run)
        jrp.start()

        jrp.join(task.execution_timeout)
        logger.debug('TaskRunner process finished')

        if jrp.is_alive():
            # If process is still alive after jr.join(job_max_runtime), kill it
            try:
                jrp.terminate()
            except Exception:
                # thread does not have terminate method
                pass
            msg = ('Function exceeded maximum time of {} seconds and was '
                   'killed'.format(task.execution_timeout))
            raise TimeoutError('HANDLER', msg)

        if show_memory_peak:
            mm_handler_conn.send('STOP')
            memory_monitor.join()
            peak_memory_usage = int(mm_handler_conn.recv())
            logger.info("Peak memory usage: {}".format(sizeof_fmt(peak_memory_usage)))
            call_status.response['peak_memory_usage'] = peak_memory_usage

        if not handler_conn.poll():
            logger.error('No completion message received from JobRunner process')
            logger.debug('Assuming memory overflow...')
            # Only 1 message is returned by jobrunner when it finishes.
            # If no message, this means that the jobrunner process was killed.
            # 99% of times the jobrunner is killed due an OOM, so we assume here an OOM.
            msg = 'Function exceeded maximum memory and was killed'
            raise MemoryError('HANDLER', msg)

        if os.path.exists(task.stats_file):
            with open(task.stats_file, 'r') as fid:
                for l in fid.readlines():
                    key, value = l.strip().split(" ", 1)
                    try:
                        call_status.response[key] = float(value)
                    except Exception:
                        call_status.response[key] = value
                    if key in ['exception', 'exc_pickle_fail', 'result', 'new_futures']:
                        call_status.response[key] = eval(value)

    except Exception:
        # internal runtime exceptions
        print('----------------------- EXCEPTION !-----------------------')
        traceback.print_exc(file=sys.stdout)
        print('----------------------------------------------------------')
        call_status.response['exception'] = True

        pickled_exc = pickle.dumps(sys.exc_info())
        pickle.loads(pickled_exc)  # this is just to make sure they can be unpickled
        call_status.response['exc_info'] = str(pickled_exc)

    finally:
        call_status.response['worker_end_tstamp'] = time.time()

        # Flush log stream and save it to the call status
        task.log_stream.flush()
        with open(task.log_file, 'rb') as lf:
            log_str = base64.b64encode(zlib.compress(lf.read())).decode()
            call_status.response['logs'] = log_str

        call_status.send('__end__')

        # Unset specific env vars
        for key in task.extra_env:
            os.environ.pop(key, None)
        os.environ.pop('__LITHOPS_TOTAL_EXECUTORS', None)

        logger.info("Finished")


class CallStatus:

    def __init__(self, lithops_config, internal_storage):
        self.config = lithops_config
        self.rabbitmq_monitor = self.config['lithops'].get('rabbitmq_monitor', False)
        self.store_status = strtobool(os.environ.get('__LITHOPS_STORE_STATUS', 'True'))
        self.internal_storage = internal_storage
        self.response = {
            'exception': False,
            'activation_id': os.environ.get('__LITHOPS_ACTIVATION_ID'),
            'python_version': os.environ.get("PYTHON_VERSION")
        }

    def send(self, event_type):
        self.response['type'] = event_type
        if self.store_status:
            if self.rabbitmq_monitor:
                self._send_status_rabbitmq()
            if not self.rabbitmq_monitor or event_type == '__end__':
                self._send_status_os()

    def _send_status_os(self):
        """
        Send the status event to the Object Storage
        """
        executor_id = self.response['executor_id']
        job_id = self.response['job_id']
        call_id = self.response['call_id']
        act_id = self.response['activation_id']

        if self.response['type'] == '__init__':
            init_key = create_init_key(JOBS_PREFIX, executor_id, job_id, call_id, act_id)
            self.internal_storage.put_data(init_key, '')

        elif self.response['type'] == '__end__':
            status_key = create_status_key(JOBS_PREFIX, executor_id, job_id, call_id)
            dmpd_response_status = json.dumps(self.response)
            drs = sizeof_fmt(len(dmpd_response_status))
            logger.info("Storing execution stats - Size: {}".format(drs))
            self.internal_storage.put_data(status_key, dmpd_response_status)

    def _send_status_rabbitmq(self):
        """
        Send the status event to RabbitMQ
        """
        dmpd_response_status = json.dumps(self.response)
        drs = sizeof_fmt(len(dmpd_response_status))

        executor_id = self.response['executor_id']
        job_id = self.response['job_id']

        rabbit_amqp_url = self.config['rabbitmq'].get('amqp_url')
        status_sent = False
        output_query_count = 0
        params = pika.URLParameters(rabbit_amqp_url)
        job_key = create_job_key(executor_id, job_id)
        exchange = 'lithops-{}'.format(job_key)

        while not status_sent and output_query_count < 5:
            output_query_count = output_query_count + 1
            try:
                connection = pika.BlockingConnection(params)
                channel = connection.channel()
                channel.exchange_declare(exchange=exchange, exchange_type='fanout', auto_delete=True)
                channel.basic_publish(exchange=exchange, routing_key='',
                                      body=dmpd_response_status)
                connection.close()
                logger.info("Execution status sent to rabbitmq - Size: {}".format(drs))
                status_sent = True
            except Exception as e:
                logger.error("Unable to send status to rabbitmq")
                logger.error(str(e))
                logger.info('Retrying to send status to rabbitmq')
                time.sleep(0.2)


def memory_monitor_worker(mm_conn, delay=0.01):
    peak = 0

    logger.debug("Starting memory monitor")

    def make_measurement(peak):
        mem = get_memory_usage(formatted=False) + 5*1024**2
        if mem > peak:
            peak = mem
        return peak

    while not mm_conn.poll(delay):
        try:
            peak = make_measurement(peak)
        except Exception:
            break

    try:
        peak = make_measurement(peak)
    except Exception as e:
        logger.error('Memory monitor: {}'.format(e))
    mm_conn.send(peak)
