#
# Copyright Cloudlab URV 2021
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

from types import SimpleNamespace
from typing import Any

import pika

from lithops.monitoring.status import MessageCallStatus


class RabbitmqCallStatus(MessageCallStatus):
    """
    Reports the status of a call by publishing it to RabbitMQ, which reaches
    the client faster, and falls back to the Object Storage at the end
    """

    service_name = 'RabbitMQ'

    def __init__(self, job: SimpleNamespace, internal_storage):
        super().__init__(job, internal_storage)
        self._amqp = None

    @property
    def pikaparams(self):
        """
        Connection parameters, read from the config the first time they
        are needed. Nothing is opened here
        """
        amqp_url = (self.config.get('rabbitmq') or {}).get('amqp_url')
        return pika.URLParameters(amqp_url)

    def _connect(self):
        connection = pika.BlockingConnection(self.pikaparams)
        return connection, connection.channel()

    def _channel(self) -> Any:
        """
        The channel to publish through.

        Opened once and kept for the whole worker process, since opening one
        costs some 150 times what publishing through it does, and a worker
        runs the calls of its chunk one after another. The broker drops a
        connection that has been idle past the heartbeat, and a long
        function is exactly that, so one that is no longer open is replaced
        rather than reused
        """
        if self._amqp is None:
            self._amqp = self.obtain_client('_amqp', self._connect)

        connection, channel = self._amqp
        if connection.is_open and channel.is_open:
            return channel

        self._drop_channel()
        self._amqp = self.obtain_client('_amqp', self._connect)
        return self._amqp[1]

    def _drop_channel(self) -> None:
        """
        Forgets the connection, here and in the process cache, and closes
        it: one that just failed must not be handed to the next call
        """
        amqp, self._amqp = self._amqp, None
        self.discard_client('_amqp')
        if amqp is None:
            return
        for closeable in reversed(amqp):
            try:
                if closeable.is_open:
                    closeable.close()
            except Exception:
                pass

    def close(self) -> None:
        """
        Leaves a shared connection open for the next call of the chunk, and
        closes one this call built for itself
        """
        if '_amqp' in self._own_clients:
            self._drop_channel()
        self._amqp = None

    def _publish(self, payload: str) -> None:
        try:
            channel = self._channel()
            for queue in self._targets():
                channel.basic_publish(
                    exchange='',
                    routing_key=queue,
                    body=payload
                )
        except Exception:
            # The connection is broken, or was never opened. Dropped here so
            # that the retry of _send(), and the next call of this worker,
            # do not publish into it again
            self._drop_channel()
            raise
