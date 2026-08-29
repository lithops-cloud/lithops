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
import json
import time
import logging
from tblib import pickling_support
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Iterator

from lithops.utils import monitoring_queue_name, sizeof_fmt
from lithops.storage.utils import create_status_key, create_init_key


pickling_support.install()

logger = logging.getLogger(__name__)


def create_call_status(job: SimpleNamespace, internal_storage) -> 'CallStatus':
    """Creates a call status class based on the monitoring backend"""
    monitoring_backend = job.config['lithops']['monitoring'].lower()
    try:
        status_cls = _STATUS_CLASSES[monitoring_backend]
    except KeyError as exc:
        raise ValueError(
            f'Unknown monitoring backend: {monitoring_backend}'
        ) from exc
    return status_cls(job, internal_storage)


class CallStatus:
    """
    Status of a single call, reported to the client both when the task starts
    and when it finishes
    """

    def __init__(self, job: SimpleNamespace, internal_storage):
        self.job = job
        self.config = job.config
        self.internal_storage = internal_storage

        self.status = {
            'exception': False,
            'activation_id': os.environ.get('__LITHOPS_ACTIVATION_ID'),
            'python_version': os.environ.get("PYTHON_VERSION"),
            'worker_start_tstamp': job.start_tstamp,
            'host_submit_tstamp': job.host_submit_tstamp,
            'call_id': job.call_id,
            'job_id': job.job_id,
            'executor_id': job.executor_id,
            'chunksize': job.chunksize
        }

        is_warm = os.environ.get('WARM_CONTAINER', '').lower() in {
            '1', 'true', 'yes'
        }
        self.status['worker_cold_start'] = not is_warm
        if not is_warm:
            os.environ['WARM_CONTAINER'] = 'True'

    def add(self, key: str, value: Any) -> None:
        """ Adds data to the call status"""
        self.status[key] = value

    def send_init_event(self) -> None:
        """ Sends the init event"""
        self.status['type'] = '__init__'
        self._send()

    def send_finish_event(self) -> None:
        """ Sends the finish event"""
        self.status['type'] = '__end__'
        self._send()


class StorageCallStatus(CallStatus):
    """Reports the status of a call by writing it to the Object Storage"""

    def _send(self) -> None:
        """
        Sends the status event to the Object Storage
        """
        executor_id = self.status['executor_id']
        job_id = self.status['job_id']
        call_id = self.status['call_id']
        act_id = self.status['activation_id']

        if self.status['type'] == '__init__':
            init_key = create_init_key(executor_id, job_id, call_id, act_id)
            self.internal_storage.put_data(init_key, '')

        elif self.status['type'] == '__end__':
            status_key = create_status_key(executor_id, job_id, call_id)
            dmpd_response_status = json.dumps(self.status)
            logger.info(
                f"Storing execution stats - "
                f"Size: {sizeof_fmt(len(dmpd_response_status))}"
            )
            self.internal_storage.put_data(status_key, dmpd_response_status)


class RabbitmqCallStatus(StorageCallStatus):
    """
    Reports the status of a call by publishing it to RabbitMQ, which reaches
    the client faster, and falls back to the Object Storage at the end
    """
    MAX_ATTEMPTS = 5

    def __init__(self, job: SimpleNamespace, internal_storage):
        super().__init__(job, internal_storage)

        rabbit_amqp_url = self.config['rabbitmq'].get('amqp_url')
        self.pikaparams = pika.URLParameters(rabbit_amqp_url)

    @contextmanager
    def _create_channel(self) -> Iterator[Any]:
        """
        Creates a rabbitmq channel, closed along with its connection
        """
        connection = pika.BlockingConnection(self.pikaparams)
        channel = connection.channel()
        try:
            yield channel
        finally:
            channel.close()
            connection.close()

    def _queue_names(self):
        """
        Returns the name of every queue this status has to be published to,
        which the client worked out and sent along with the job.

        The fallback only reaches the queue of this very executor: a payload
        without the chain cannot say which executors are waiting further up,
        so a nested job would go unnoticed by its ancestors
        """
        queues = getattr(self.job, 'monitoring_queues', None)
        if queues:
            return list(queues)

        logger.warning(
            'The job carries no monitoring queues, reporting only to the '
            f'queue of {self.job.executor_id}'
        )
        return [monitoring_queue_name(self.job.executor_id)]

    def _send(self) -> None:
        """
        Sends the status event to RabbitMQ
        """
        dmpd_response_status = json.dumps(self.status)
        queues = self._queue_names()
        exc = None

        for _ in range(self.MAX_ATTEMPTS):
            try:
                with self._create_channel() as channel:
                    for queue in queues:
                        channel.basic_publish(
                            exchange='',
                            routing_key=queue,
                            body=dmpd_response_status
                        )
                logger.info(
                    f"Execution status sent to RabbitMQ - "
                    f"Size: {sizeof_fmt(len(dmpd_response_status))}"
                )
                break
            except Exception as e:
                exc = e
                time.sleep(0.2)
        else:
            logger.error(
                f"Could not send the execution status to RabbitMQ after "
                f"{self.MAX_ATTEMPTS} attempts: {exc}"
            )

        if self.status['type'] == '__end__':
            super()._send()


_STATUS_CLASSES = {
    'storage': StorageCallStatus,
    'rabbitmq': RabbitmqCallStatus,
}
