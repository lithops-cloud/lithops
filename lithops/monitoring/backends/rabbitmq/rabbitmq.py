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

import logging

import pika

from lithops.monitoring.monitor import PollingMessageMonitor
from lithops.utils import log_prefix

logger = logging.getLogger(__name__)


class RabbitmqMonitor(PollingMessageMonitor):
    """
    Job monitor that learns the status of every call from the messages the
    workers publish to a RabbitMQ queue.

    Messages are consumed through ``BlockingChannel.consume()``, a
    generator over a real AMQP consumer: the broker pushes messages with
    prefetch, and the generator hands back control when nothing has
    arrived for a while, which is what lets the shared polling loop expire
    futures and notice stop(). Reading with ``basic_get`` instead would
    cost a round trip per message.
    """

    def __init__(
            self,
            executor_id,
            internal_storage,
            token_bucket_q,
            job_chunksize,
            generate_tokens,
            config
    ):
        super().__init__(
            executor_id,
            internal_storage,
            token_bucket_q,
            job_chunksize,
            generate_tokens,
            config
        )

        self.rabbit_amqp_url = config.get('amqp_url')
        self.pikaparams = pika.URLParameters(self.rabbit_amqp_url)
        # The connection is opened here, on the thread that builds the
        # monitor, and used by the monitor thread from then on. Only one of
        # the two ever touches it, which is what a pika BlockingConnection
        # needs; stop() is the exception, and hands its close over with
        # add_callback_threadsafe()
        self.queue = self.monitoring_queue_name()
        self.connection = None
        self.channel = None
        self.consumer = None
        self._create_resources()

    def _create_resources(self):
        """
        Opens the connection and declares the queue the workers publish to
        """
        logger.debug(
            f'{log_prefix(self.executor_id)} - Creating RabbitMQ queue {self.queue}'
        )
        self.connection = pika.BlockingConnection(self.pikaparams)
        channel = self.connection.channel()
        channel.queue_declare(queue=self.queue, auto_delete=True)
        channel.close()

    def _consume(self, timeout):
        """
        Returns the consumer generator, opening it on the first call and
        after a connection has been lost. The queue is declared again on
        the way, since an auto-delete queue is gone once its last consumer
        has left
        """
        if self.consumer is None:
            if self.connection is None or self.connection.is_closed:
                self._create_resources()
            self.channel = self.connection.channel()
            self.consumer = self.channel.consume(
                self.queue, auto_ack=True, inactivity_timeout=timeout
            )
        return self.consumer

    def _discard_consumer(self):
        """
        Forgets the consumer and its connection without touching the
        broker, for when they are already broken
        """
        self.consumer = None
        self.channel = None
        connection, self.connection = self.connection, None
        if connection is None:
            return
        try:
            # stop() may already have closed it to unblock the consumer,
            # and pika logs an error of its own for a second close
            if connection.is_open:
                connection.close()
        except Exception:
            pass

    def stop(self):
        """
        Asks the loop to exit and unblocks the consumer, which is otherwise
        waiting for the broker to push until the inactivity timeout. The
        connection belongs to the monitor thread, so the close is handed to
        it instead of being done here
        """
        self.should_run = False
        connection = self.connection
        if connection is None:
            return
        try:
            connection.add_callback_threadsafe(connection.close)
        except Exception:
            # The connection is already gone, or its loop is not running,
            # and the inactivity timeout ends the wait either way
            pass

    def _receive_messages(self, timeout):
        """
        Yields whatever the broker has pushed so far, and returns once it
        goes quiet for ``timeout`` seconds
        """
        try:
            for method, _properties, body in self._consume(timeout):
                if method is None:
                    # Nothing arrived within the inactivity timeout
                    return
                yield body.decode('utf-8')
        except Exception:
            # The channel or the connection is gone. Drop them so the next
            # round opens a new consumer, and let the loop report it
            self._discard_consumer()
            raise

    def _close_receiver(self):
        """
        Cancels the consumer and closes its connection. Runs on the monitor
        thread, the only one allowed to touch a pika BlockingConnection
        """
        connection = self.connection
        if self.channel is not None and connection is not None \
                and connection.is_open:
            try:
                self.channel.cancel()
            except Exception:
                logger.debug(
                    f'{log_prefix(self.executor_id)} - Could not cancel the '
                    'RabbitMQ consumer',
                    exc_info=True,
                )
        self._discard_consumer()

    def _delete_resources(self):
        """
        Deletes the queue of this executor.

        Called from the thread that shuts the executor down, so it uses a
        connection of its own rather than the one the monitor thread was
        consuming with
        """
        connection = pika.BlockingConnection(self.pikaparams)
        try:
            channel = connection.channel()
            channel.queue_delete(queue=self.queue)
            channel.close()
            logger.debug(
                f'{log_prefix(self.executor_id)} - Deleted RabbitMQ queue '
                f'{self.queue}'
            )
        finally:
            connection.close()
