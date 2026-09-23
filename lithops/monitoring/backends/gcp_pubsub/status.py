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

from lithops.monitoring.backends.gcp_pubsub import gcp_pubsub as pubsub_backend
from lithops.monitoring.backends.gcp_pubsub.gcp_pubsub import _topic_path
from lithops.monitoring.status import MessageCallStatus


class GcpPubsubCallStatus(MessageCallStatus):
    """
    Reports the status of a call by publishing it to Pub/Sub, which
    reaches the client faster, and falls back to Object Storage at the end
    """

    service_name = 'Pub/Sub'
    MAX_MESSAGE_SIZE = 10 * 1000 * 1000

    def __init__(self, job, internal_storage):
        super().__init__(job, internal_storage)
        self.project = (
            self.config.get('gcp_pubsub') or {}
        ).get('project_name')

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

    def _publish_to(self, target: str, payload: str) -> None:
        # The monitor that reads the topic created it before any worker was
        # invoked. One that is not there belongs to a reader that is gone,
        # and the NotFound is what tells the caller so
        future = self.publisher.publish(
            _topic_path(self.project, target), payload.encode('utf-8')
        )
        future.result(timeout=10)
