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

from lithops.monitoring.backends.gcp_pubsub import gcp_pubsub as pubsub_backend
from lithops.monitoring.backends.gcp_pubsub.gcp_pubsub import _topic_path
from lithops.monitoring.monitor import is_named_error
from lithops.monitoring.status import MessageCallStatus

logger = logging.getLogger(__name__)


class GcpPubsubCallStatus(MessageCallStatus):
    """
    Reports the status of a call by publishing it to Pub/Sub, which
    reaches the client faster, and falls back to Object Storage at the end
    """

    service_name = 'Pub/Sub'

    def __init__(self, job, internal_storage):
        super().__init__(job, internal_storage)
        self.project = (
            self.config.get('gcp_pubsub') or {}
        ).get('project_name')
        self._topics = set()

    @cached_property
    def publisher(self):
        """
        Built on the first status rather than in __init__, and then kept for
        the whole worker process: a call that never reports opens nothing,
        and the calls that follow publish through the same publisher. See
        MessageCallStatus.obtain_client()
        """
        def build():
            publisher, _subscriber = pubsub_backend.pubsub_clients(
                self.config.get('gcp_pubsub') or {}
            )
            return publisher

        return self.obtain_client('publisher', build)

    def _ensure_topic(self, name):
        """
        The path of a topic, created if it is not there.

        The monitor of the executor created the topic before any worker was
        invoked, so AlreadyExists is the normal answer here; anything else
        is a real failure and is left for _send() to retry and report
        """
        path = _topic_path(self.project, name)
        if path in self._topics:
            return path
        try:
            self.publisher.create_topic(name=path)
        except Exception as exc:
            if not is_named_error(exc, 'AlreadyExists', 'PermissionDenied'):
                raise
            if is_named_error(exc, 'PermissionDenied'):
                # A worker that may publish but not create topics is fine,
                # as long as the topic is already there
                logger.debug(
                    f'Not allowed to create the Pub/Sub topic {name}; '
                    'assuming it exists'
                )
        self._topics.add(path)
        return path

    def close(self) -> None:
        self._topics.clear()
        super().close()

    def _publish(self, payload: str) -> None:
        data = payload.encode('utf-8')
        for name in self._targets():
            future = self.publisher.publish(self._ensure_topic(name), data)
            future.result(timeout=10)
