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

from lithops.monitoring.monitor import (
    PollingMessageMonitor,
    is_named_error,
)
from lithops.utils import log_prefix

logger = logging.getLogger(__name__)


def _topic_path(project, name):
    return f'projects/{project}/topics/{name}'


def _subscription_path(project, name):
    return f'projects/{project}/subscriptions/{name}'


def pubsub_clients(config):
    """Builds the Pub/Sub publisher and subscriber clients"""
    from google.cloud import pubsub_v1

    kwargs = {}
    path = config.get('credentials_path')
    if path:
        from google.oauth2 import service_account
        kwargs['credentials'] = (
            service_account.Credentials.from_service_account_file(path)
        )
    return (
        pubsub_v1.PublisherClient(**kwargs),
        pubsub_v1.SubscriberClient(**kwargs),
    )


class GcpPubsubMonitor(PollingMessageMonitor):
    """
    Job monitor that learns the status of every call from messages the
    workers publish to a Pub/Sub topic.

    The topic and its pull subscription are created with the executor
    and deleted in cleanup(). stop() keeps them so a later map() on the
    same executor can reuse them.
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
        self.queue = self.monitoring_queue_name()
        self.project = config.get('project_name')
        self.publisher, self.subscriber = pubsub_clients(config)
        self.topic_path = _topic_path(self.project, self.queue)
        self.subscription_path = _subscription_path(self.project, self.queue)
        self._create_resources()

    def _create_resources(self):
        logger.debug(
            f'{log_prefix(self.executor_id)} - Creating Pub/Sub topic '
            f'{self.queue}'
        )
        try:
            self.publisher.create_topic(name=self.topic_path)
        except Exception as exc:
            if not is_named_error(exc, 'AlreadyExists'):
                raise
        try:
            self.subscriber.create_subscription(
                name=self.subscription_path,
                topic=self.topic_path,
                ack_deadline_seconds=30,
            )
        except Exception as exc:
            if not is_named_error(exc, 'AlreadyExists'):
                raise

    def _delete_resources(self):
        if self.subscription_path:
            try:
                self.subscriber.delete_subscription(
                    subscription=self.subscription_path
                )
                logger.debug(
                    f'{log_prefix(self.executor_id)} - Deleted Pub/Sub '
                    f'subscription {self.queue}'
                )
            except Exception:
                logger.warning(
                    f'{log_prefix(self.executor_id)} - Could not delete '
                    f'Pub/Sub subscription {self.queue}',
                    exc_info=True,
                )
            self.subscription_path = None
        if self.topic_path:
            try:
                self.publisher.delete_topic(topic=self.topic_path)
                logger.debug(
                    f'{log_prefix(self.executor_id)} - Deleted Pub/Sub '
                    f'topic {self.queue}'
                )
            except Exception:
                logger.warning(
                    f'{log_prefix(self.executor_id)} - Could not delete '
                    f'Pub/Sub topic {self.queue}',
                    exc_info=True,
                )
            self.topic_path = None

    def _receive_messages(self, timeout):
        if not self.subscription_path:
            return
        try:
            response = self.subscriber.pull(
                subscription=self.subscription_path,
                max_messages=10,
                timeout=max(1.0, float(timeout)),
                retry=None,
            )
        except Exception as exc:
            if is_named_error(exc, 'DeadlineExceeded', 'RetryError'):
                return
            if self.should_run:
                logger.warning(
                    f'{log_prefix(self.executor_id)} - Pub/Sub pull failed',
                    exc_info=True,
                )
            return

        # Acknowledged only once every status of the batch has been
        # applied: an exception on the way leaves them unacknowledged, and
        # Pub/Sub hands them over again when the ack deadline is up
        received = getattr(response, 'received_messages', None) or []
        ack_ids = []
        for item in received:
            data = item.message.data
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            yield data
            ack_ids.append(item.ack_id)
        if ack_ids:
            try:
                self.subscriber.acknowledge(
                    subscription=self.subscription_path,
                    ack_ids=ack_ids,
                )
            except Exception:
                logger.warning(
                    f'{log_prefix(self.executor_id)} - Could not ack '
                    'Pub/Sub messages after applying them',
                    exc_info=True,
                )
