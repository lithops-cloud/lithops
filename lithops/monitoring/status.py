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

import atexit
import json
import logging
import os
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable, Hashable

from lithops.monitoring.backends import resolve_backend
from lithops.storage.utils import create_init_key, create_status_key
from lithops.utils import monitoring_queue_name, sizeof_fmt

logger = logging.getLogger(__name__)

#: Set to 0 to build a client per call instead of keeping one for the
#: process. The escape hatch for a runtime where a client that outlives the
#: call does not survive the fork of the next one
REUSE_CLIENTS_ENV = 'LITHOPS_REUSE_MONITORING_CLIENTS'

_SHARED_CLIENTS = {}
_SHARED_LOCK = threading.RLock()
_ATEXIT_REGISTERED = False


def reuse_clients() -> bool:
    """
    Whether one client serves every call of this process.

    A worker runs the calls of its chunk one after another, and building a
    client per call costs far more than publishing the status does: opening
    an AMQP connection is some 150 times the cost of the publish it carries
    """
    return os.environ.get(REUSE_CLIENTS_ENV, '1').strip().lower() not in {
        '0', 'false', 'no'
    }


def _release_client(client: Any, service: str = 'monitoring') -> None:
    """Closes a client with whichever of close() and stop() its SDK offers"""
    if client is None:
        return
    for method in ('close', 'stop'):
        release = getattr(client, method, None)
        if release is None:
            continue
        try:
            release()
        except Exception as e:
            logger.debug(f'Could not {method}() the {service} client: {e}')
        return


def shared_client(key: Hashable, factory: Callable[[], Any]) -> Any:
    """
    The client kept for this process under ``key``, built on first use
    """
    global _ATEXIT_REGISTERED
    with _SHARED_LOCK:
        client = _SHARED_CLIENTS.get(key)
        if client is None:
            client = _SHARED_CLIENTS[key] = factory()
            if not _ATEXIT_REGISTERED:
                _ATEXIT_REGISTERED = True
                atexit.register(close_shared_clients)
        return client


def drop_shared_client(key: Hashable) -> Any:
    """Forgets the client under ``key``, and returns it so it can be closed"""
    with _SHARED_LOCK:
        return _SHARED_CLIENTS.pop(key, None)


def close_shared_clients() -> None:
    """Releases every client this process kept. Runs at interpreter exit"""
    with _SHARED_LOCK:
        clients = list(_SHARED_CLIENTS.items())
        _SHARED_CLIENTS.clear()
    for key, client in clients:
        _release_client(client, str(key))


def create_call_status(job: SimpleNamespace, internal_storage) -> 'CallStatus':
    """
    Creates the call status class of the configured monitoring backend.

    The backend is resolved exactly as the client resolves it, so a config
    that does not name one reports through the same default the client
    listens on
    """
    from lithops.monitoring.backends import load_backend_attr, resolve_backend

    backend = resolve_backend(job.config)
    status_cls = load_backend_attr(backend, 'CallStatus')
    return status_cls(job, internal_storage)


class CallStatus:
    """
    Status of a single call, reported to the client both when the task starts
    and when it finishes.

    A monitoring backend exports a subclass of this class as ``CallStatus``.
    Workers only call :meth:`send_init_event` and :meth:`send_finish_event`;
    the subclass implements :meth:`_send`.
    """

    def __init__(self, job: SimpleNamespace, internal_storage):
        self.job = job
        self.config = job.config
        self.internal_storage = internal_storage

        self.status = {
            'exception': False,
            'activation_id': os.environ.get('__LITHOPS_ACTIVATION_ID'),
            'python_version': os.environ.get("PYTHON_VERSION"),
            'worker_start_tstamp': job.start_tstamp,
            'host_submit_tstamp': job.host_submit_tstamp,
            'call_id': job.call_id,
            'job_id': job.job_id,
            'executor_id': job.executor_id,
            'chunksize': job.chunksize
        }

        is_warm = os.environ.get('WARM_CONTAINER', '').lower() in {
            '1', 'true', 'yes'
        }
        self.status['worker_cold_start'] = not is_warm
        if not is_warm:
            os.environ['WARM_CONTAINER'] = 'True'

    def add(self, key: str, value: Any) -> None:
        """ Adds data to the call status"""
        self.status[key] = value

    def send_init_event(self) -> None:
        """ Sends the init event"""
        self.status['type'] = '__init__'
        self._send()

    def send_finish_event(self) -> None:
        """ Sends the finish event"""
        self.status['type'] = '__end__'
        self._send()

    def _send(self) -> None:
        raise NotImplementedError


class StorageCallStatus(CallStatus):
    """Reports the status of a call by writing it to the Object Storage"""

    def _send(self) -> None:
        """
        Sends the status event to the Object Storage
        """
        executor_id = self.status['executor_id']
        job_id = self.status['job_id']
        call_id = self.status['call_id']
        act_id = self.status['activation_id']

        if self.status['type'] == '__init__':
            init_key = create_init_key(executor_id, job_id, call_id, act_id)
            self.internal_storage.put_data(init_key, '')

        elif self.status['type'] == '__end__':
            status_key = create_status_key(executor_id, job_id, call_id)
            dmpd_response_status = json.dumps(self.status)
            logger.info(
                f"Storing execution stats - "
                f"Size: {sizeof_fmt(len(dmpd_response_status))}"
            )
            self.internal_storage.put_data(status_key, dmpd_response_status)


class MessageCallStatus(StorageCallStatus):
    """
    Reports the status of a call by publishing it to a message service,
    which reaches the client faster, and falls back to Object Storage
    at the end.

    Subclasses implement :meth:`_publish`.
    """

    MAX_ATTEMPTS = 5
    RETRY_SLEEP = 0.2
    MAX_RETRY_SLEEP = 5
    service_name = 'message service'

    def __init__(self, job: SimpleNamespace, internal_storage):
        super().__init__(job, internal_storage)
        # Clients this object built for itself, which nothing else uses and
        # close() therefore has to release. A shared one outlives the call
        self._own_clients = set()

    def _client_key(self, name: str) -> Hashable:
        """
        What makes a shared client shareable: the class, the name of the
        client, and the settings it was built from. A process that reports
        to two brokers must not publish to one of them through the other's
        connection
        """
        backend = resolve_backend(self.config)
        section = (self.config or {}).get(backend) or {}
        settings = tuple(sorted(
            (str(key), repr(value)) for key, value in section.items()
        ))
        return (type(self).__name__, name, settings)

    def obtain_client(self, name: str, factory: Callable[[], Any]) -> Any:
        """
        The client to publish through, built on first use.

        Kept for the whole process unless reuse is turned off, in which case
        each call builds and releases its own. Subclasses reach this through
        a cached_property, so the client is looked up once per call
        """
        if reuse_clients():
            return shared_client(self._client_key(name), factory)
        client = factory()
        self._own_clients.add(name)
        return client

    def discard_client(self, name: str) -> None:
        """
        Drops the client under ``name`` and closes it.

        A shared one is dropped from the process cache as well: a connection
        that just failed must not be handed to the next call
        """
        self.__dict__.pop(name, None)
        if name in self._own_clients:
            self._own_clients.discard(name)
            return
        _release_client(
            drop_shared_client(self._client_key(name)), self.service_name
        )

    def _send(self) -> None:
        """
        Publishes the status, and writes an __end__ to the Object Storage as
        well.

        The storage copy is what the client reads back when the message is
        lost, which a message service that delivers at most once can do; see
        MessageMonitor._storage_sweep()
        """
        dmpd_response_status = json.dumps(self.status)
        exc = None

        for attempt in range(self.MAX_ATTEMPTS):
            try:
                self._publish(dmpd_response_status)
                logger.info(
                    f"Execution status sent to {self.service_name} - "
                    f"Size: {sizeof_fmt(len(dmpd_response_status))}"
                )
                exc = None
                break
            except Exception as e:
                exc = e
                if attempt == self.MAX_ATTEMPTS - 1:
                    break
                # Backed off, so that the attempts span a broker hiccup
                # instead of being spent within the same second
                time.sleep(min(
                    self.RETRY_SLEEP * (2 ** attempt), self.MAX_RETRY_SLEEP
                ))

        if exc is not None:
            logger.error(
                f"Could not send the execution status to {self.service_name} "
                f"after {self.MAX_ATTEMPTS} attempts: {exc}"
            )

        if self.status['type'] == '__end__':
            super()._send()

    def _targets(self) -> list:
        """
        Names this status has to be published to: every executor up the
        chain, ending with this one. The client sends the list with the
        job; without it only this executor can be reached.
        """
        queues = getattr(self.job, 'monitoring_queues', None)
        if queues:
            return list(queues)

        logger.warning(
            'The job carries no monitoring queues, reporting only to the '
            f'queue of {self.job.executor_id}'
        )
        return [monitoring_queue_name(self.job.executor_id)]

    def send_finish_event(self) -> None:
        """
        Sends the last status of the call and releases the client with it:
        the object is not used again, and a worker that keeps warm would
        otherwise leave one connection per call behind
        """
        try:
            super().send_finish_event()
        finally:
            try:
                self.close()
            except Exception as e:
                logger.debug(
                    f'Could not close the {self.service_name} client: {e}'
                )

    def close(self) -> None:
        """
        Releases the clients this call owns, after its last status.

        A client kept for the process is left alone: the next call of the
        chunk publishes through it, which is the point of keeping it
        """
        self._release_cached(*sorted(self._own_clients))

    def _release_cached(self, *names: str) -> None:
        """
        Releases the clients a subclass built with ``cached_property``,
        taken out of the instance dict rather than through the attribute so
        that closing one that was never needed does not build it
        """
        for name in names:
            client = self.__dict__.pop(name, None)
            self._own_clients.discard(name)
            _release_client(client, self.service_name)

    def _publish(self, payload: str) -> None:
        raise NotImplementedError
