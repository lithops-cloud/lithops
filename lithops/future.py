#
# Copyright 2018 PyWren Team
# Copyright IBM Corp. 2020
# Copyright Cloudlab URV 2020
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

import os
import sys
import time
import zlib
import base64
import pickle
import logging
import traceback
from six import reraise

from lithops.storage import InternalStorage
from lithops.storage.utils import (
    check_storage_path,
    get_storage_path,
    create_job_key
)
from lithops.constants import FN_LOG_FILE, LOGS_DIR
from lithops.utils import log_prefix

logger = logging.getLogger(__name__)

_STAT_KEY_PREFIXES = ('func', 'host', 'worker')


def _stats_from_prefixed_keys(mapping: dict) -> dict:
    """
    Picks the entries that hold a statistic, told apart from the rest of the
    status by their key prefix
    """
    return {
        key: mapping[key]
        for key in mapping
        if any(key.startswith(p) for p in _STAT_KEY_PREFIXES)
    }


def _pickle_from_encoded(encoded: str):
    """
    Unpickles a value the worker put in the call status. It travels as the
    repr() of its pickle, so eval() is what turns it back into bytes
    """
    return pickle.loads(eval(encoded))


class ResponseFuture:
    """
    Result of a Lithops invocation. Exposes execution status
    and the return value once it is available.
    """

    class State:
        New = "New"
        Invoked = "Invoked"
        Running = "Running"
        Ready = "Ready"
        Success = "Success"
        Error = "Error"
        Done = "Done"
        Unknown = "Unknown"

    def __init__(self, call_id, job, job_metadata, storage_config):
        self.call_id = call_id
        self.job_id = job.job_id
        self.job_key = job.job_key
        self.executor_id = job.executor_id
        self.function_name = job.function_name
        self.execution_timeout = job.execution_timeout
        self.runtime_name = job.runtime_name
        self.runtime_memory = job.runtime_memory
        self.activation_id = None
        self.stats = {}
        self.logs = None

        self._storage_config = storage_config
        self._produce_output = True
        self._read = False
        self._state = self.State.New
        self._exception = Exception()
        self._handler_exception = False
        self._new_futures = None
        self._traceback = None
        self._call_status = None
        self._call_output = None
        self._host_status_done_tstamp = None
        self._status_query_count = 0
        self._output_query_count = 0

        self.stats.update(_stats_from_prefixed_keys(job_metadata))
        self._storage_path = get_storage_path(self._storage_config)

    def _id_prefix(self) -> str:
        """
        Identity of the job this call belongs to, for the log messages
        """
        return log_prefix(self.executor_id, self.job_id)

    def _set_state(self, new_state: str) -> None:
        self._state = new_state

    def cancel(self):
        raise NotImplementedError("Cannot cancel dispatched jobs")

    def cancelled(self):
        raise NotImplementedError("Cannot cancel dispatched jobs")

    @property
    def new(self):
        return self._state == self.State.New

    @property
    def invoked(self):
        return self._state == self.State.Invoked

    @property
    def running(self):
        return self._state == self.State.Running

    @property
    def ready(self):
        return self._state == self.State.Ready

    @property
    def error(self):
        return self._state == self.State.Error

    @property
    def success(self):
        return self._state in (self.State.Success, self.State.Error)

    @property
    def done(self):
        return self._state in (
            self.State.Done,
            self.State.Error,
            self.State.Unknown,
        )

    @property
    def futures(self):
        return self._new_futures is not None

    def _set_invoked(self):
        """Set the future as invoked"""
        self._set_state(self.State.Invoked)

    def _set_running(self, call_status):
        """Set the future as running"""
        self._call_status = call_status
        self.activation_id = self._call_status['activation_id']
        self._set_state(self.State.Running)

    def _set_exception(self):
        """Set the future as error"""
        self._read = True
        self._host_status_done_tstamp = time.time()
        if not self.done:
            self._set_state(self.State.Unknown)

    def _set_ready(self, call_status):
        """Set the future as ready"""
        self._call_status = call_status
        self._host_status_done_tstamp = time.time()
        self._set_state(self.State.Ready)

    def _set_futures(self, call_status):
        """Set the future as futures"""
        self._call_status = call_status
        self._host_status_done_tstamp = time.time()
        self.status(throw_except=False)
        self._set_state(self.State.Ready)

    def _set_mapreduce(self):
        """Set the future as mapreduce map"""
        self._read = True
        self._produce_output = False
        if self.success:
            self._set_state(self.State.Done)

    def _query_call_status(self, internal_storage):
        """
        Reads the status the worker wrote, counting the query. Returns None
        while the call has not finished
        """
        status = internal_storage.get_call_status(
            self.executor_id, self.job_id, self.call_id
        )
        self._status_query_count += 1
        return status

    def _query_call_output(self, internal_storage):
        """
        Reads the result the worker wrote, counting the query. Returns None
        while it is not there yet
        """
        output = internal_storage.get_call_output(
            self.executor_id, self.job_id, self.call_id
        )
        self._output_query_count += 1
        return output

    def _write_activation_logs(self) -> None:
        """
        Replays the log of the activation, which travels compressed in the
        status, into the job log and the global function log
        """
        encoded = self._call_status['logs'].encode()
        self.logs = zlib.decompress(base64.b64decode(encoded)).decode()
        job_key = create_job_key(self.executor_id, self.job_id)
        log_file = os.path.join(LOGS_DIR, job_key + '.log')
        header = f"Activation: '{self.runtime_name}' ({self.activation_id})\n[\n"
        # Every line is indented but the last one, so that the bracket that
        # closes the activation stays at the left margin
        newline_count = self.logs.count('\n')
        indented = self.logs.replace('\r', '').replace(
            '\n', '\n    ', newline_count - 1
        )
        formatted = header + '    ' + indented + ']\n\n'
        os.makedirs(LOGS_DIR, exist_ok=True)
        for path in (log_file, FN_LOG_FILE):
            with open(path, 'a') as lf:
                lf.write(formatted)

    def _poll_until_ready(self, internal_storage, wait_dur_sec, check_only):
        """
        Waits for the worker to write the status of the call, unless only
        checking, in which case it returns whatever there is right away
        """
        self._call_status = self._query_call_status(internal_storage)
        if check_only:
            return self._call_status
        while self._call_status is None:
            time.sleep(wait_dur_sec)
            self._call_status = self._query_call_status(internal_storage)
        self._host_status_done_tstamp = time.time()
        return self._call_status

    def _raise_call_exception(self, throw_except):
        """
        Rebuilds the exception the function raised and, unless the caller
        asked not to, re-raises it with the traceback it had in the worker
        """
        self._set_state(self.State.Error)
        self._exception = _pickle_from_encoded(
            self._call_status['exc_info']
        )

        if not self._call_status.get('exc_pickle_fail', False):
            fn_exctype = self._exception[0]
            fn_exc = self._exception[1]
            # The worker marks its own failures with a HANDLER first argument.
            # They carry no user traceback worth printing, so the marker is
            # dropped and only the message is kept
            if fn_exc.args and fn_exc.args[0] == "HANDLER":
                self._handler_exception = True
                try:
                    del fn_exc.errno
                except Exception:
                    pass
                fn_exc.args = (fn_exc.args[1],)
        else:
            fn_exctype = Exception
            fn_exc = Exception(self._exception['exc_value'])
            self._exception = (
                fn_exctype,
                fn_exc,
                self._exception['exc_traceback'],
            )

        logger.warning(
            f'{self._id_prefix()} - CallID: {self.call_id} - '
            f'There was an exception - Activation ID: {self.activation_id} - {fn_exctype.__name__}'
        )

        # Reraising here would print a traceback pointing at this file, so the
        # hook prints the one the function had in the worker instead. Anything
        # else raised afterwards restores the default hook
        def exception_hook(exctype, exc, trcbck):
            # Ctrl+C and sys.exit() are the interpreter going down, not the
            # function failing. Formatting them here reads source files
            # through linecache, so a second Ctrl+C lands inside this hook
            # and turns into "Error in sys.excepthook"
            if issubclass(exctype, (KeyboardInterrupt, SystemExit)):
                sys.excepthook = sys.__excepthook__
                sys.__excepthook__(exctype, exc, trcbck)
            elif exctype == fn_exctype and str(exc) == str(fn_exc):
                if self._handler_exception:
                    logger.warning(
                        f'Exception: {fn_exctype.__name__} - {fn_exc}'
                    )
                else:
                    traceback.print_exception(*self._exception)
            else:
                sys.excepthook = sys.__excepthook__
                traceback.print_exception(exctype, exc, trcbck)

        if throw_except:
            sys.excepthook = exception_hook
            reraise(*self._exception)
        return None

    def _record_status_stats(self) -> float:
        """
        Copies the statistics of the call status into the future and returns
        how long the function ran for
        """
        self.stats['host_status_done_tstamp'] = (
            self._host_status_done_tstamp or time.time()
        )
        self.stats['host_status_query_count'] = self._status_query_count
        self.stats.update(_stats_from_prefixed_keys(self._call_status))

        exec_time = round(
            self.stats['worker_end_tstamp']
            - self.stats['worker_start_tstamp'],
            8,
        )
        self.stats['worker_exec_time'] = exec_time
        return exec_time

    def _resolve_new_futures(self) -> None:
        """
        Adopts the futures the function returned: this call produces no
        result of its own, the client has to wait for those instead
        """
        new_futures = _pickle_from_encoded(
            self._call_status['new_futures']
        )
        if isinstance(new_futures, ResponseFuture):
            self._new_futures = [new_futures]
        else:
            self._new_futures = new_futures

    def _read_inline_result(self) -> None:
        """
        Takes the result the worker embedded in the status, which saves the
        client one storage request
        """
        self._call_output = _pickle_from_encoded(
            self._call_status['result']
        )
        self.stats['host_result_done_tstamp'] = time.time()
        self.stats['host_result_query_count'] = 0
        logger.debug(
            f'{self._id_prefix()} - Got output from call '
            f'{self.call_id} - Activation ID: {self.activation_id}'
        )

    def status(
        self,
        throw_except=True,
        internal_storage=None,
        check_only=False,
        wait_dur_sec=1,
    ):
        """
        Return the status returned by the call.
        If the call raised an exception, this method will raise
        the same exception. If the future is cancelled before
        completing then CancelledError will be raised.

        :param check_only: Return None immediately if job is
            not complete. Default False.
        :param throw_except: Reraise exception if call raised.
            Default true.
        :param internal_storage: Storage handler to poll cloud
            storage. Default None.
        :param wait_dur_sec: Time interval between each check

        :return: Result of the call.
        :raises CancelledError: If the job is cancelled
            before completed.
        :raises TimeoutError: If job is not complete after
            `timeout` seconds.
        """
        if self._state == self.State.New:
            raise ValueError("task not yet invoked")

        if self.success or self.done:
            return self._call_status

        needs_fetch = (
            self._call_status is None
            or self._call_status['type'] == '__init__'
        )
        if needs_fetch:
            if internal_storage is None:
                internal_storage = InternalStorage(self._storage_config)
            check_storage_path(
                internal_storage.get_storage_config(),
                self._storage_path,
            )
            status = self._poll_until_ready(
                internal_storage, wait_dur_sec, check_only
            )
            if check_only:
                return status

        self.activation_id = self._call_status['activation_id']

        if 'logs' in self._call_status:
            self._write_activation_logs()

        exec_time = self._record_status_stats()

        logger.debug(
            f'{self._id_prefix()} - Got status from call '
            f'{self.call_id} - Activation ID: {self.activation_id} '
            f'- Time: {exec_time:.2f} seconds'
        )

        if self._call_status['exception']:
            return self._raise_call_exception(throw_except)

        if 'new_futures' in self._call_status and not self._new_futures:
            self._resolve_new_futures()
        elif self._call_status['func_result_size'] == 0:
            self._produce_output = False

        if 'result' in self._call_status:
            self._read_inline_result()

        if self._call_output is not None or not self._produce_output:
            self._set_state(self.State.Done)
        else:
            self._set_state(self.State.Success)

        return self._call_status

    def _fetch_call_output(self, internal_storage, retries, wait_dur_sec):
        """
        Reads the result of the call from the storage, retrying while it is
        not there. The status can arrive before the result. Returns None if
        it never shows up
        """
        call_output = self._query_call_output(internal_storage)
        while (
            call_output is None
            and self._output_query_count < retries
        ):
            time.sleep(wait_dur_sec)
            call_output = self._query_call_output(internal_storage)
        return call_output

    def result(
        self,
        throw_except=True,
        internal_storage=None,
        retries=10,
        wait_dur_sec=1,
    ):
        """
        Return the value returned by the call.
        If the call raised an exception, this method will raise
        the same exception. If the future is cancelled before
        completing then CancelledError will be raised.

        :param throw_except: Reraise exception if call raised.
            Default true.
        :param internal_storage: Storage handler to poll cloud
            storage. Default None.
        :param retries: Number of times to check if the result
            file is in the storage
        :param wait_dur_sec: Time interval between each retry

        :return: Result of the call.
        :raises CancelledError: If the job is cancelled
            before completed.
        :raises TimeoutError: If job is not complete after
            `timeout` seconds.
        """
        if self._state == self.State.New:
            raise ValueError("Task not yet invoked")

        if not self.done and internal_storage is None:
            internal_storage = InternalStorage(self._storage_config)

        self.status(
            throw_except=throw_except,
            internal_storage=internal_storage,
            wait_dur_sec=wait_dur_sec,
        )

        if self.futures:
            self._call_output = self._new_futures
            self._set_state(self.State.Done)

        if self.done:
            return self._call_output

        if self._call_output is None:
            call_output = self._fetch_call_output(
                internal_storage, retries, wait_dur_sec
            )

            if call_output is None:
                if throw_except:
                    raise Exception(
                        f'{self._id_prefix()} - Unable to get '
                        f'the result from call {self.call_id} - Activation ID: {self.activation_id}'
                    )
                self._set_state(self.State.Error)
                return None

            self._call_output = pickle.loads(call_output)
            self.stats['host_result_done_tstamp'] = time.time()
            self.stats['host_result_query_count'] = self._output_query_count
            logger.debug(
                f'{self._id_prefix()} - Got output from call '
                f'{self.call_id} - Activation ID: {self.activation_id}'
            )

        self._set_state(self.State.Done)
        return self._call_output
