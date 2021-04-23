import os
import pika
import json
import time
import logging
from tblib import pickling_support

import lithops.worker
from lithops.utils import sizeof_fmt
from lithops.storage.utils import create_status_key, create_job_key,\
    create_init_key
from lithops.constants import JOBS_PREFIX
from distutils.util import strtobool

pickling_support.install()

logger = logging.getLogger(__name__)


def create_call_status(job, internal_storage):
    """ Creates a call status class based on the monitoring backend"""
    monitoring_backend = job.config['lithops']['monitoring']
    Status = getattr(lithops.worker.status, '{}CallStatus'
                     .format(monitoring_backend.capitalize()))
    return Status(job, internal_storage)


class CallStatus:

    def __init__(self, job, internal_storage):
        self.job = job
        self.config = job.config
        self.internal_storage = internal_storage

        self.status = {
            'exception': False,
            'activation_id': os.environ.get('__LITHOPS_ACTIVATION_ID'),
            'python_version': os.environ.get("PYTHON_VERSION"),
            'worker_start_tstamp': time.time(),
            'host_submit_tstamp': job.host_submit_tstamp,
            'call_id': job.id,
            'job_id': job.job_id,
            'executor_id': job.executor_id
        }

        if strtobool(os.environ.get('WARM_CONTAINER', 'False')):
            self.status['warm_container'] = True
        else:
            self.status['warm_container'] = False
            os.environ['WARM_CONTAINER'] = 'True'

    def add(self, key, value):
        """ Adds data to the call status"""
        self.status[key] = value

    def send_init_event(self):
        """ Sends the init event"""
        self.status['type'] = '__init__'
        self._send()

    def send_finish_event(self):
        """ Sends the finish event"""
        self.status['type'] = '__end__'
        self._send()


class StorageCallStatus(CallStatus):

    def _send(self):
        """
        Send the status event to the Object Storage
        """
        executor_id = self.status['executor_id']
        job_id = self.status['job_id']
        call_id = self.status['call_id']
        act_id = self.status['activation_id']

        if self.status['type'] == '__init__':
            init_key = create_init_key(JOBS_PREFIX, executor_id, job_id, call_id, act_id)
            self.internal_storage.put_data(init_key, '')

        elif self.status['type'] == '__end__':
            status_key = create_status_key(JOBS_PREFIX, executor_id, job_id, call_id)
            dmpd_response_status = json.dumps(self.status)
            drs = sizeof_fmt(len(dmpd_response_status))
            logger.info("Storing execution stats - Size: {}".format(drs))
            self.internal_storage.put_data(status_key, dmpd_response_status)


class RabbitmqCallStatus(StorageCallStatus):

    def _send(self):
        """
        Send the status event to RabbitMQ
        """
        dmpd_response_status = json.dumps(self.status)
        drs = sizeof_fmt(len(dmpd_response_status))

        executor_id = self.status['executor_id']
        job_id = self.status['job_id']

        rabbit_amqp_url = self.config['rabbitmq'].get('amqp_url')
        status_sent = False
        output_query_count = 0
        params = pika.URLParameters(rabbit_amqp_url)
        job_key = create_job_key(executor_id, job_id)
        queue = 'lithops-{}'.format(job_key)

        while not status_sent and output_query_count < 5:
            output_query_count = output_query_count + 1
            try:
                connection = pika.BlockingConnection(params)
                channel = connection.channel()
                channel.basic_publish(exchange='', routing_key=queue, body=dmpd_response_status)
                logger.info("Execution status sent to RabbitMQ - Size: {}".format(drs))
                status_sent = True
            except Exception:
                time.sleep(0.2)
            channel.close()
            connection.close()

        if self.status['type'] == '__end__':
            super()._send()
