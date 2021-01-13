#
# Copyright 2018 PyWren Team
# Copyright IBM Corp. 2019
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
import pika
import time
import json
import pickle
import logging
import traceback
from threading import Thread
from multiprocessing import Process, Pipe
from distutils.util import strtobool
from tblib import pickling_support

from lithops import version
from lithops.utils import sizeof_fmt
from lithops.config import extract_storage_config
from lithops.storage import InternalStorage
from lithops.worker.jobrunner import JobRunner
from lithops.worker.utils import get_memory_usage
from lithops.constants import JOBS_PREFIX, LITHOPS_TEMP_DIR
from lithops.storage.utils import create_output_key, create_status_key,\
    create_init_key, create_job_key

pickling_support.install()

logging.getLogger('pika').setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)

LITHOPS_LIBS_PATH = '/action/lithops/libs'


def function_handler(event):
    start_tstamp = time.time()

    logger.debug("Action handler started")

    extra_env = event.get('extra_env', {})
    os.environ.update(extra_env)
    os.environ.update({'LITHOPS_WORKER': 'True',
                       'PYTHONUNBUFFERED': 'True'})

    config = event['config']
    call_id = event['call_id']
    job_id = event['job_id']
    executor_id = event['executor_id']
    job_key = create_job_key(executor_id, job_id)
    logger.info("Execution ID: {}/{}".format(job_key, call_id))

    runtime_name = event['runtime_name']
    runtime_memory = event['runtime_memory']
    execution_timeout = event['execution_timeout']

    logger.debug("Runtime name: {}".format(runtime_name))
    if runtime_memory:
        logger.debug("Runtime memory: {}MB".format(runtime_memory))
    logger.debug("Function timeout: {}s".format(execution_timeout))

    func_key = event['func_key']
    data_key = event['data_key']
    data_byte_range = event['data_byte_range']

    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)

    call_status = CallStatus(config, internal_storage)
    call_status.response['host_submit_tstamp'] = event['host_submit_tstamp']
    call_status.response['worker_start_tstamp'] = start_tstamp
    context_dict = {
        'python_version': os.environ.get("PYTHON_VERSION"),
        'call_id': call_id,
        'job_id': job_id,
        'executor_id': executor_id,
        'activation_id': os.environ.get('__LITHOPS_ACTIVATION_ID')
    }
    call_status.response.update(context_dict)

    show_memory_peak = strtobool(os.environ.get('SHOW_MEMORY_PEAK', 'False'))

    try:
        if version.__version__ != event['lithops_version']:
            msg = ("Lithops version mismatch. Host version: {} - Runtime version: {}"
                   .format(event['lithops_version'], version.__version__))
            raise RuntimeError('HANDLER', msg)

        # send init status event
        call_status.send('__init__')

        # call_status.response['free_disk_bytes'] = free_disk_space("/tmp")
        custom_env = {'LITHOPS_CONFIG': json.dumps(config),
                      '__LITHOPS_SESSION_ID': '-'.join([job_key, call_id]),
                      'PYTHONPATH': "{}:{}".format(os.getcwd(), LITHOPS_LIBS_PATH)}
        os.environ.update(custom_env)

        jobrunner_stats_dir = os.path.join(LITHOPS_TEMP_DIR, storage_config['bucket'],
                                           JOBS_PREFIX, job_key, call_id)
        os.makedirs(jobrunner_stats_dir, exist_ok=True)
        jobrunner_stats_filename = os.path.join(jobrunner_stats_dir, 'jobrunner.stats.txt')

        jobrunner_config = {'lithops_config': config,
                            'call_id':  call_id,
                            'job_id':  job_id,
                            'executor_id':  executor_id,
                            'func_key': func_key,
                            'data_key': data_key,
                            'data_byte_range': data_byte_range,
                            'output_key': create_output_key(JOBS_PREFIX, executor_id, job_id, call_id),
                            'stats_filename': jobrunner_stats_filename}

        if show_memory_peak:
            mm_handler_conn, mm_conn = Pipe()
            memory_monitor = Thread(target=memory_monitor_worker, args=(mm_conn, ))
            memory_monitor.start()

        handler_conn, jobrunner_conn = Pipe()
        jobrunner = JobRunner(jobrunner_config, jobrunner_conn, internal_storage)
        logger.debug('Starting JobRunner process')
        local_execution = strtobool(os.environ.get('__LITHOPS_LOCAL_EXECUTION', 'False'))
        jrp = Thread(target=jobrunner.run) if local_execution else Process(target=jobrunner.run)
        jrp.start()

        jrp.join(execution_timeout)
        logger.debug('JobRunner process finished')

        if jrp.is_alive():
            # If process is still alive after jr.join(job_max_runtime), kill it
            try:
                jrp.terminate()
            except Exception:
                # thread does not have terminate method
                pass
            msg = ('Function exceeded maximum time of {} seconds and was '
                   'killed'.format(execution_timeout))
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

        if os.path.exists(jobrunner_stats_filename):
            with open(jobrunner_stats_filename, 'r') as fid:
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
        logger.error('----------------------- EXCEPTION !-----------------------')
        traceback.print_exc(file=sys.stdout)
        logger.error('----------------------------------------------------------')
        call_status.response['exception'] = True

        pickled_exc = pickle.dumps(sys.exc_info())
        pickle.loads(pickled_exc)  # this is just to make sure they can be unpickled
        call_status.response['exc_info'] = str(pickled_exc)

    finally:
        call_status.response['worker_end_tstamp'] = time.time()
        call_status.send('__end__')

        # Unset specific env vars
        for key in extra_env:
            os.environ.pop(key, None)
        os.environ.pop('__LITHOPS_TOTAL_EXECUTORS', None)

        logger.info("Finished")


class CallStatus:

    def __init__(self, lithops_config, internal_storage):
        self.config = lithops_config
        self.rabbitmq_monitor = self.config['lithops'].get('rabbitmq_monitor', False)
        self.store_status = strtobool(os.environ.get('__LITHOPS_STORE_STATUS', 'True'))
        self.internal_storage = internal_storage
        self.response = {'exception': False}

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
