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

from functools import cached_property

from lithops.monitoring.backends.redis import redis as redis_backend
from lithops.monitoring.status import MessageCallStatus


class RedisCallStatus(MessageCallStatus):
    """
    Reports the status of a call by pushing it onto a Redis list, which
    reaches the client faster, and falls back to Object Storage at the end
    """

    service_name = 'Redis'

    @cached_property
    def client(self):
        """
        Built on the first status rather than in __init__, and then kept for
        the whole worker process: a call that never reports opens nothing,
        and the calls that follow publish through the same connection. See
        MessageCallStatus.obtain_client()
        """
        return self.obtain_client(
            'client',
            lambda: redis_backend.redis_client(self.config.get('redis') or {}),
        )

    def _publish(self, payload: str) -> None:
        for queue in self._targets():
            self.client.rpush(queue, payload)
