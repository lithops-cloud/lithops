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

import inspect
import logging
from functools import lru_cache

from lithops.monitoring.monitor import PollingMessageMonitor
from lithops.utils import log_prefix

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _accepted_params():
    """
    The keyword arguments ``redis.Redis()`` takes. Read off the signature
    once: a worker builds a client per call, and every executor builds one
    for its monitor
    """
    import redis

    accepted = set(inspect.signature(redis.Redis.__init__).parameters)
    accepted.discard('self')
    return frozenset(accepted)


def _redis_params(config):
    """
    Keeps of a lithops ``redis`` section only what ``redis.Redis()`` takes.

    An allow list rather than a deny list: the section is shared with the
    storage, multiprocessing and joblib backends, which put keys of their
    own in it, and ``redis.Redis()`` raises TypeError on any it does not
    know
    """
    accepted = _accepted_params()
    return {
        key: value for key, value in config.items() if key in accepted
    }


def redis_client(config):
    """
    Builds a Redis client from a lithops ``redis`` section.

    Every caller gets a client, and so a connection pool, of its own: the
    monitor closes its client when it stops, and it must not take the
    connections of the storage or multiprocessing backends down with it
    """
    import redis

    return redis.Redis(**_redis_params(config))


def _decode(payload):
    if isinstance(payload, bytes):
        return payload.decode('utf-8')
    return payload


class RedisMonitor(PollingMessageMonitor):
    """
    Job monitor that learns the status of every call from messages the
    workers push onto a Redis list.

    The list is deleted in cleanup(), not in stop(), so a later map()
    on the same executor can reuse it.
    """

    #: How many statuses one read takes off the list. BLPOP hands over one
    #: at a time, so the rest of the batch comes off in a single LPOP: it is
    #: what keeps a map of n calls from costing n round trips, which over a
    #: network is the whole cost of monitoring it
    BATCH_SIZE = 1000

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
        self.client = redis_client(config)
        # LPOP takes a count from Redis 6.2 on. An older server answers with
        # an error, and the fallback is one LPOP per status, pipelined
        self._lpop_count = True
        self._can_batch = True
        self._create_resources()

    def _create_resources(self):
        logger.debug(
            f'{log_prefix(self.executor_id)} - Using Redis list {self.queue}'
        )
        try:
            self.client.ping()
        except Exception:
            logger.error(
                f'{log_prefix(self.executor_id)} - Could not reach Redis',
                exc_info=True,
            )
            raise

    def _delete_resources(self):
        try:
            self.client.delete(self.queue)
            logger.debug(
                f'{log_prefix(self.executor_id)} - Deleted Redis list {self.queue}'
            )
        except Exception:
            logger.warning(
                f'{log_prefix(self.executor_id)} - Could not delete Redis '
                f'list {self.queue}',
                exc_info=True,
            )

    def stop(self):
        """
        Asks the loop to exit and drops the connections under the BLPOP that
        is waiting on the broker, which ends it at once.

        Waiting for the poll timeout instead costs a second or two on every
        stop, and stop() runs after every wait() that finds its futures
        done, not only at shutdown. The pool being torn down is this
        monitor's own: redis_client() builds a client per caller, so the
        storage, multiprocessing and joblib backends keep theirs
        """
        self.should_run = False
        try:
            self.client.connection_pool.disconnect()
        except Exception:
            logger.debug(
                f'{log_prefix(self.executor_id)} - Could not drop the Redis '
                'connections when stopping',
                exc_info=True,
            )

    def _drain(self, limit):
        """
        Takes up to ``limit`` further statuses off the list in one round
        trip, without blocking.

        ``LPOP key <count>`` returns only what is there, so it costs the
        same whether the list holds one status or a thousand. Servers older
        than Redis 6.2 do not take the count, and clients that cannot do
        either fall back to one status per read
        """
        if limit <= 0:
            return []

        if self._lpop_count:
            try:
                return self.client.lpop(self.queue, limit) or []
            except Exception as e:
                self._lpop_count = False
                logger.debug(
                    f'{log_prefix(self.executor_id)} - This Redis does not '
                    f'take a count on LPOP ({e}); falling back to a pipeline'
                )

        if not self._can_batch:
            return []
        try:
            pipe = self.client.pipeline()
            for _ in range(min(limit, 64)):
                pipe.lpop(self.queue)
            return [item for item in pipe.execute() if item is not None]
        except Exception as e:
            self._can_batch = False
            logger.debug(
                f'{log_prefix(self.executor_id)} - This Redis client cannot '
                f'pipeline ({e}); reading one status per round trip'
            )
            return []

    def _receive_messages(self, timeout):
        """
        Blocks until a status shows up, then takes whatever else is already
        on the list along with it
        """
        item = self.client.blpop(self.queue, timeout=max(1, int(timeout)))
        if not item:
            return
        _key, payload = item
        yield _decode(payload)
        for payload in self._drain(self.BATCH_SIZE - 1):
            yield _decode(payload)

    def _close_receiver(self):
        """
        Releases the client of this monitor once its loop is done. The list
        is deleted through cleanup() afterwards, on a connection redis-py
        opens again by itself
        """
        try:
            self.client.close()
        except Exception:
            logger.debug(
                f'{log_prefix(self.executor_id)} - Could not close the Redis '
                'client',
                exc_info=True,
            )
