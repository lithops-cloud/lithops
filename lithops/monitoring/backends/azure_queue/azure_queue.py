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

import hashlib
import logging
import re

from lithops.monitoring.monitor import (
    PollingMessageMonitor,
    is_named_error,
)
from lithops.utils import log_prefix

logger = logging.getLogger(__name__)


#: Azure Storage queue names: 3 to 63 lowercase letters, digits and single
#: hyphens, starting and ending with a letter or a digit
_INVALID_QUEUE_CHARS = re.compile(r'[^a-z0-9-]+')
QUEUE_NAME_MAX_LEN = 63


def azure_queue_name(name):
    """
    Turns a lithops queue name into one Azure Queue Storage accepts.

    Names are lowercase, 3 to 63 letters, digits and single hyphens, and
    start and end with a letter or a digit. A name that goes past that is
    kept unique by ending it with a digest of the original
    """
    cleaned = _INVALID_QUEUE_CHARS.sub('-', name.lower())
    cleaned = re.sub(r'-{2,}', '-', cleaned).strip('-')

    if len(cleaned) > QUEUE_NAME_MAX_LEN:
        digest = hashlib.sha1(name.encode('utf-8')).hexdigest()[:8]
        keep = QUEUE_NAME_MAX_LEN - len(digest) - 1
        cleaned = f'{cleaned[:keep].rstrip("-")}-{digest}'

    if len(cleaned) < 3:
        cleaned = f'{cleaned}-queue'.lstrip('-')

    return cleaned


def queue_service(config):
    """Builds a QueueServiceClient from a lithops ``azure_queue`` section"""
    from azure.storage.queue import QueueServiceClient
    account = config['storage_account_name']
    return QueueServiceClient(
        account_url=f'https://{account}.queue.core.windows.net',
        credential=config['storage_account_key'],
    )


class AzureQueueMonitor(PollingMessageMonitor):
    """
    Job monitor that learns the status of every call from messages the
    workers send to an Azure Storage queue.

    The queue is created with the executor and deleted in cleanup().
    stop() keeps it so a later map() on the same executor can reuse it.
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
        self.queue = azure_queue_name(self.monitoring_queue_name())
        self.service = queue_service(config)
        self.queue_client = None
        self._create_resources()

    def _create_resources(self):
        logger.debug(
            f'{log_prefix(self.executor_id)} - Creating Azure queue '
            f'{self.queue}'
        )
        try:
            self.queue_client = self.service.create_queue(self.queue)
        except Exception as exc:
            if not is_named_error(exc, 'ResourceExistsError'):
                raise
            self.queue_client = self.service.get_queue_client(self.queue)
        if self.queue_client is None:
            self.queue_client = self.service.get_queue_client(self.queue)

    def _delete_resources(self):
        try:
            self.service.delete_queue(self.queue)
            logger.debug(
                f'{log_prefix(self.executor_id)} - Deleted Azure queue '
                f'{self.queue}'
            )
        except Exception:
            logger.warning(
                f'{log_prefix(self.executor_id)} - Could not delete Azure '
                f'queue {self.queue}',
                exc_info=True,
            )
        self.queue_client = None

    def _receive_messages(self, timeout):
        if not self.queue_client:
            return
        # Deleted only once the status has been applied: an exception on the
        # way leaves the message on the queue, and Azure hands it over again
        # when the visibility timeout is up
        messages = self.queue_client.receive_messages(
            messages_per_page=16,
            visibility_timeout=30,
        )
        for message in messages:
            content = message.content
            if isinstance(content, bytes):
                content = content.decode('utf-8')
            yield content
            try:
                self.queue_client.delete_message(message)
            except Exception:
                logger.warning(
                    f'{log_prefix(self.executor_id)} - Could not delete '
                    'an Azure queue message after applying it',
                    exc_info=True,
                )
