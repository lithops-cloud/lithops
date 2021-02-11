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
from lithops.worker.jobrunner import JobRunner
from lithops.worker.utils import get_memory_usage, LogStream
from lithops.constants import JOBS_PREFIX, LITHOPS_TEMP_DIR
from lithops.utils import sizeof_fmt, setup_lithops_logger, is_unix_system
from lithops.storage.utils import create_status_key, create_job_key,\
    create_init_key

pickling_support.install()

logging.getLogger('pika').setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)

LITHOPS_LIBS_PATH = '/action/lithops/libs'


class ShutdownSentinel():
    """Put an instance of this class on the queue to shut it down"""
    pass


def function_handler(payload):
    job = SimpleNamespace(**payload)

    manager = SyncManager()
    manager.start()
    job_queue = manager.Queue()
    job_runners = []

    processes = min(job.worker_processes, len(job.call_ids))
    logger.info("Starting {} processes".format(processes))

    for runner_id in range(processes):
        p = mp.Process(target=process_runner, args=(runner_id, job_queue))
        job_runners.append(p)
        p.start()

    for call_id in job.call_ids:
        data_byte_range = job.data_byte_ranges.pop(0)
        logger.info('Going to execute job {}-{}'.format(job.job_key, call_id))
        job_queue.put((job, call_id, data_byte_range))

    for i in range(processes):
        job_queue.put(ShutdownSentinel())

    for runner in job_runners:
        runner.join()

    manager.shutdown()


def process_runner(runner_id, job_queue):
    """
    Listens the job_queue and executes the jobs
    """
    logger.info('Worker process {} started'.format(runner_id))

    while True:
        event = job_queue.get(block=True)
        if isinstance(event, ShutdownSentinel):
            break

        job, call_id, data_byte_range = event

        bucket = job.config['lithops']['storage_bucket']
        job.job_dir = os.path.join(LITHOPS_TEMP_DIR, bucket, JOBS_PREFIX, job.job_key, call_id)
        job.log_file = os.path.join(job.job_dir, 'execution.log')
        os.makedirs(job.job_dir, exist_ok=True)

        job.call_id = call_id
        job.data_byte_range = data_byte_range

        old_stderr = sys.stderr
        old_stdout = sys.stdout
        log_strem = open(job.log_file, 'a')
        sys.stderr = LogStream(log_strem)
        sys.stdout = LogStream(log_strem)
        run_job(job)
        log_strem.close()
        sys.stderr = old_stderr
        sys.stdout = old_stdout


def run_job(job):
    """
    Runs a single job within a separate process
    """
    start_tstamp = time.time()
    setup_lithops_logger(job.log_level)

    logger.info("Lithops v{} - Starting execution".format(__version__))
    logger.info("Execution ID: {}/{}".format(job.job_key, job.call_id))
    logger.debug("Runtime name: {}".format(job.runtime_name))
    if job.runtime_memory:
        logger.debug("Runtime memory: {}MB".format(job.runtime_memory))
    logger.debug("Function timeout: {}s".format(job.execution_timeout))

    env = job.extra_env
    env['LITHOPS_WORKER'] = 'True'
    env['PYTHONUNBUFFERED'] = 'True'
    env['LITHOPS_CONFIG'] = json.dumps(job.config)
    env['PYTHONPATH'] = "{}:{}".format(os.getcwd(), LITHOPS_LIBS_PATH)
    env['__LITHOPS_SESSION_ID'] = '-'.join([job.job_key, job.call_id])
    os.environ.update(env)

    storage_config = extract_storage_config(job.config)
    internal_storage = InternalStorage(storage_config)

    call_status = CallStatus(job.config, internal_storage)
    call_status.response['worker_start_tstamp'] = start_tstamp
    call_status.response['host_submit_tstamp'] = job.host_submit_tstamp
    call_status.response['call_id'] = job.call_id
    call_status.response['job_id'] = job.job_id
    call_status.response['executor_id'] = job.executor_id

    show_memory_peak = strtobool(os.environ.get('SHOW_MEMORY_PEAK', 'False'))

    try:
        if __version__ != job.lithops_version:
            msg = ("Lithops version mismatch. Host version: {} - Runtime version: {}"
                   .format(job.lithops_version, __version__))
            raise RuntimeError('HANDLER', msg)

        # send init status event
        call_status.send('__init__')

        if show_memory_peak:
            mm_handler_conn, mm_conn = Pipe()
            memory_monitor = Thread(target=memory_monitor_worker, args=(mm_conn, ))
            memory_monitor.start()

        job.jr_stats_file = os.path.join(job.job_dir, 'jobrunner.stats.txt')
        handler_conn, jobrunner_conn = Pipe()
        jobrunner = JobRunner(job, jobrunner_conn, internal_storage)
        logger.debug('Starting JobRunner process')
        jrp = Process(target=jobrunner.run) if is_unix_system() else Thread(target=jobrunner.run)
        jrp.start()

        jrp.join(job.execution_timeout)
        logger.debug('JobRunner process finished')

        if jrp.is_alive():
            # If process is still alive after jr.join(job_max_runtime), kill it
            try:
                jrp.terminate()
            except Exception:
                # thread does not have terminate method
                pass
            msg = ('Function exceeded maximum time of {} seconds and was '
                   'killed'.format(job.execution_timeout))
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

        if os.path.exists(job.jr_stats_file):
            with open(job.jr_stats_file, 'r') as fid:
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

        with open(job.log_file, 'rb') as lf:
            log_str = base64.b64encode(zlib.compress(lf.read())).decode()
            call_status.response['logs'] = log_str

        call_status.send('__end__')

        # Unset specific env vars
        for key in job.extra_env:
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
                logger.info('Retrying to send status to rabbitmq...')
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
