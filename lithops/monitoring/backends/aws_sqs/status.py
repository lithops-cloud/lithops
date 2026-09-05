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
from functools import cached_property

from lithops.monitoring.backends.aws_sqs import aws_sqs as sqs_backend
from lithops.monitoring.monitor import is_named_error
from lithops.monitoring.status import MessageCallStatus

logger = logging.getLogger(__name__)


class SqsCallStatus(MessageCallStatus):
    """
    Reports the status of a call by sending it to SQS, which reaches the
    client faster, and falls back to Object Storage at the end
    """

    service_name = 'SQS'

    def __init__(self, job, internal_storage):
        super().__init__(job, internal_storage)
        self._urls = {}

    @cached_property
    def client(self):
        """
        Built on the first status rather than in __init__, and then kept for
        the whole worker process: a call that never reports opens nothing,
        and the calls that follow publish through the same client. See
        MessageCallStatus.obtain_client()
        """
        return self.obtain_client(
            'client',
            lambda: sqs_backend.sqs_client(self.config.get('aws_sqs') or {}),
        )

    def _queue_url(self, name):
        """
        The URL of a queue by name, looked up once per call.

        The monitor of the executor created the queue before any worker was
        invoked, so this normally just resolves it; it is created here only
        when it is really not there, which is what a status published to an
        executor further up the chain can run into
        """
        url = self._urls.get(name)
        if url:
            return url
        try:
            url = self.client.get_queue_url(QueueName=name)['QueueUrl']
        except Exception as exc:
            if not is_named_error(
                exc, 'QueueDoesNotExist', 'NonExistentQueue'
            ):
                raise
            logger.debug(f'The SQS queue {name} is not there; creating it')
            url = self.client.create_queue(QueueName=name)['QueueUrl']
        self._urls[name] = url
        return url

    def close(self) -> None:
        self._urls.clear()
        super().close()

    def _publish(self, payload: str) -> None:
        for name in self._targets():
            self.client.send_message(
                QueueUrl=self._queue_url(name),
                MessageBody=payload,
            )
