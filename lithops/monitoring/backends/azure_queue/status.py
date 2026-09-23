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

from functools import cached_property

from lithops.monitoring.backends.azure_queue import azure_queue as azure_backend
from lithops.monitoring.backends.azure_queue.azure_queue import azure_queue_name
from lithops.monitoring.status import MessageCallStatus


class AzureQueueCallStatus(MessageCallStatus):
    """
    Reports the status of a call by sending it to Azure Queue Storage,
    which reaches the client faster, and falls back to Object Storage
    at the end
    """

    service_name = 'Azure Queue'
    #: The service takes 64 KiB per message, measured once the SDK has
    #: encoded it: XML-escaped text by default, base64 when the queue client
    #: is configured so, which is 4/3 of the text. Three quarters of the
    #: limit fits either way
    MAX_MESSAGE_SIZE = 48 * 1024

    def __init__(self, job, internal_storage):
        super().__init__(job, internal_storage)
        self._queues = {}

    @cached_property
    def service(self):
        """
        Built on the first status rather than in __init__, and then kept for
        the whole worker process: a call that never reports opens nothing,
        and the calls that follow publish through the same client. See
        MessageCallStatus.obtain_client()
        """
        return self.obtain_client(
            'service',
            lambda: azure_backend.queue_service(
                self.config.get('azure_queue') or {}
            ),
        )

    def _queue(self, name):
        name = azure_queue_name(name)
        client = self._queues.get(name)
        if client:
            return client
        client = self.service.get_queue_client(name)
        self._queues[name] = client
        return client

    def close(self) -> None:
        # The per-queue clients hang off the service client, and are rebuilt
        # from it in a couple of microseconds; the service itself is what is
        # expensive to open, and it is kept for the process
        for client in self._queues.values():
            try:
                client.close()
            except Exception:
                pass
        self._queues.clear()
        super().close()

    def _publish_to(self, target: str, payload: str) -> None:
        self._queue(target).send_message(payload)
