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

from lithops.monitoring.monitor import PollingMessageMonitor
from lithops.utils import log_prefix

logger = logging.getLogger(__name__)


def sqs_client(config):
    """Builds an SQS client from a lithops ``aws_sqs`` section"""
    import boto3
    return boto3.client(
        'sqs',
        region_name=config.get('region'),
        aws_access_key_id=config.get('access_key_id'),
        aws_secret_access_key=config.get('secret_access_key'),
        aws_session_token=config.get('session_token'),
    )


class SqsMonitor(PollingMessageMonitor):
    """
    Job monitor that learns the status of every call from messages the
    workers send to an SQS queue.

    The queue is created with the executor and deleted in cleanup()
    (executor exit / lithops clean on exit). stop() keeps it: SQS
    refuses to recreate a queue of the same name for 60 seconds, and a
    later map() on the same executor would fail.
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
        self.client = sqs_client(config)
        self.queue_url = None
        self._create_resources()

    def _create_resources(self):
        logger.debug(
            f'{log_prefix(self.executor_id)} - Creating SQS queue {self.queue}'
        )
        response = self.client.create_queue(QueueName=self.queue)
        self.queue_url = response['QueueUrl']

    def _delete_resources(self):
        if not self.queue_url:
            return
        try:
            self.client.delete_queue(QueueUrl=self.queue_url)
            logger.debug(
                f'{log_prefix(self.executor_id)} - Deleted SQS queue {self.queue}'
            )
        except Exception:
            logger.warning(
                f'{log_prefix(self.executor_id)} - Could not delete SQS '
                f'queue {self.queue}',
                exc_info=True,
            )
        self.queue_url = None

    def _receive_messages(self, timeout):
        if not self.queue_url:
            return
        response = self.client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=min(20, max(1, int(timeout))),
            VisibilityTimeout=30,
        )
        # Deleted only once the status has been applied: an exception on the
        # way leaves the message on the queue, and SQS hands it over again
        # when the visibility timeout is up
        for message in response.get('Messages', []):
            yield message['Body']
            try:
                self.client.delete_message(
                    QueueUrl=self.queue_url,
                    ReceiptHandle=message['ReceiptHandle'],
                )
            except Exception:
                logger.warning(
                    f'{log_prefix(self.executor_id)} - Could not delete '
                    'an SQS message after applying it',
                    exc_info=True,
                )
