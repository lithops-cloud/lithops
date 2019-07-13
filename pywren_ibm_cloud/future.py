#
# Copyright 2018 PyWren Team
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

import time
import enum
import pickle
import logging
from pywren_ibm_cloud.storage import InternalStorage
from pywren_ibm_cloud.storage.storage_utils import check_storage_path, get_storage_path
from pywren_ibm_cloud.libs.tblib import pickling_support

pickling_support.install()
logger = logging.getLogger(__name__)


class JobState(enum.Enum):
    new = 1
    invoked = 2
    running = 3
    ready = 4
    success = 5
    futures = 6
    error = 7


class FunctionException(Exception):
    def __init__(self, executor_id, activation_id, exc, exc_msg):
        self.exception = exc
        self.exc_msg = exc_msg
        self.msg = 'ExecutorID {} - There was an exception - Activation ID: {}'.format(executor_id, activation_id)
        super().__init__(self.msg)


class ResponseFuture:

    """
    Object representing the result of a PyWren invocation. Returns the status of the
    execution and the result when available.
    """
    GET_RESULT_SLEEP_SECS = 1
    GET_RESULT_MAX_RETRIES = 10

    def __init__(self, call_id, callgroup_id, executor_id, activation_id, storage_config, invoke_metadata):
        self.call_id = call_id
        self.callgroup_id = callgroup_id
        self.executor_id = executor_id
        self.activation_id = activation_id
        self.storage_config = storage_config
        self.produce_output = True

        self._state = JobState.new
        self._exception = Exception()
        self._return_val = None
        self._new_futures = None
        self._traceback = None
        self._call_invoker_result = None

        self.run_status = None
        self.invoke_status = invoke_metadata.copy()

        self.status_query_count = 0
        self.output_query_count = 0

        self.storage_path = get_storage_path(self.storage_config)

    def _set_state(self, new_state):
        self._state = new_state

    def cancel(self):
        raise NotImplementedError("Cannot cancel dispatched jobs")

    def cancelled(self):
        raise NotImplementedError("Cannot cancel dispatched jobs")

    def running(self):
        raise NotImplementedError()

    @property
    def futures(self):
        """
        The response of a call was a FutureResponse instance.
        It has to wait to the new invocation output.
        """
        return self._state == JobState.futures

    @property
    def done(self):
        if self._state in [JobState.success, JobState.futures, JobState.error]:
            return True
        return False

    @property
    def ready(self):
        if self._state in [JobState.ready, JobState.futures, JobState.error]:
            return True
        return False

    def status(self, check_only=False, throw_except=True, internal_storage=None):
        """
        Return the status returned by the call.
        If the call raised an exception, this method will raise the same exception
        If the future is cancelled before completing then CancelledError will be raised.

        :param check_only: Return None immediately if job is not complete. Default False.
        :param throw_except: Reraise exception if call raised. Default true.
        :param storage_handler: Storage handler to poll cloud storage. Default None.
        :return: Result of the call.
        :raises CancelledError: If the job is cancelled before completed.
        :raises TimeoutError: If job is not complete after `timeout` seconds.
        """
        if self._state == JobState.new:
            raise ValueError("job not yet invoked")

        if self._state == JobState.ready or self._state == JobState.success:
            return self.run_status

        if internal_storage is None:
            internal_storage = InternalStorage(self.storage_config)

        check_storage_path(internal_storage.get_storage_config(), self.storage_path)
        call_status = internal_storage.get_call_status(self.executor_id, self.callgroup_id, self.call_id)
        self.status_query_count += 1

        if check_only is True:
            if call_status is None:
                return None

        while call_status is None:
            time.sleep(self.GET_RESULT_SLEEP_SECS)
            call_status = internal_storage.get_call_status(self.executor_id, self.callgroup_id, self.call_id)
            self.status_query_count += 1

        self.invoke_status['status_done_timestamp'] = time.time()
        self.invoke_status['status_query_count'] = self.status_query_count

        self.run_status = call_status  # this is the remote status information

        total_time = format(round(call_status['end_time'] - call_status['start_time'], 2), '.2f')

        if call_status['exception']:
            # the action handler/jobrunner/function had an exception
            self._set_state(JobState.error)
            self._exception = pickle.loads(eval(call_status['exc_info']))
            msg = None

            if not call_status.get('exc_pickle_fail', False):
                exception_args = self._exception[1].args

                if exception_args[0] == "WRONGVERSION":
                    msg = "PyWren version mismatch: remote expected version {}, local" \
                          "library is version {}".format(exception_args[2], exception_args[3])

                if exception_args[0] == "OUTATIME":
                    msg = "Process ran out of time"

                if exception_args[0] == "OUTOFMEMORY":
                    msg = "Process exceeded maximum memory and was killed"

                if exception_args[0] == "EXCPICKLEERROR":
                    msg = "PyWren was unable to pickle the exception, check function logs"
            else:
                fault = Exception(self._exception['exc_value'])
                self._exception = (Exception, fault, self._exception['exc_traceback'])

            if throw_except:
                raise FunctionException(self.executor_id, self.activation_id, self._exception, msg)
            return None

        log_msg = ('ExecutorID {} - Got status from Function {} - Activation '
                   'ID: {} - Time: {} seconds'.format(self.executor_id,
                                                      self.call_id,
                                                      self.activation_id,
                                                      str(total_time)))
        logger.debug(log_msg)
        self._set_state(JobState.ready)
        if not call_status['result'] and self.produce_output:
            # Function did not produce output
            self._set_state(JobState.success)

        if 'new_futures' in call_status:
            unused_callgroup_id, total_new_futures = call_status['new_futures'].split('/')
            if int(total_new_futures) > 0:
                self.result(throw_except=throw_except, internal_storage=internal_storage)

        return self.run_status

    def result(self, check_only=False, throw_except=True, internal_storage=None):
        """
        Return the value returned by the call.
        If the call raised an exception, this method will raise the same exception
        If the future is cancelled before completing then CancelledError will be raised.

        :param throw_except: Reraise exception if call raised. Default true.
        :param storage_handler: Storage handler to poll cloud storage. Default None.
        :return: Result of the call.
        :raises CancelledError: If the job is cancelled before completed.
        :raises TimeoutError: If job is not complete after `timeout` seconds.
        """
        if self._state == JobState.new:
            raise ValueError("job not yet invoked")

        if self._state == JobState.success:
            return self._return_val

        if self._state == JobState.futures:
            return self._new_futures

        if internal_storage is None:
            internal_storage = InternalStorage(storage_config=self.storage_config)

        self.status(check_only, throw_except, internal_storage)

        if not self.produce_output:
            return

        if self._state == JobState.success:
            return self._return_val

        if self._state == JobState.futures:
            return self._new_futures

        if self._state == JobState.error:
            if throw_except:
                raise FunctionException(self.executor_id, self.activation_id, self._exception)
            else:
                return None

        call_output_time = time.time()
        call_invoker_result = internal_storage.get_call_output(self.executor_id, self.callgroup_id, self.call_id)
        self.output_query_count += 1

        while call_invoker_result is None and self.output_query_count < self.GET_RESULT_MAX_RETRIES:
            time.sleep(self.GET_RESULT_SLEEP_SECS)
            call_invoker_result = internal_storage.get_call_output(self.executor_id, self.callgroup_id, self.call_id)
            self.output_query_count += 1

        if call_invoker_result is None:
            if throw_except:
                raise Exception('Unable to get the output of the function - Activation ID: {}'.format(self.activation_id))
            else:
                self._set_state(JobState.error)
                return None

        call_invoker_result = pickle.loads(call_invoker_result)
        call_output_time_done = time.time()
        self._call_invoker_result = call_invoker_result

        self.invoke_status['download_output_time'] = call_output_time_done - call_output_time
        self.invoke_status['output_query_count'] = self.output_query_count
        self.invoke_status['download_output_timestamp'] = call_output_time_done

        log_msg = ('ExecutorID {} - Got output from Function {} - Activation '
                   'ID: {}'.format(self.executor_id, self.call_id, self.activation_id))
        logger.debug(log_msg)

        function_result = call_invoker_result['result']

        if isinstance(function_result, ResponseFuture):
            self._new_futures = [function_result]
            self._set_state(JobState.futures)
            self.invoke_status['status_done_timestamp'] = self.invoke_status['download_output_timestamp']
            del self.invoke_status['download_output_timestamp']
            return self._new_futures

        elif type(function_result) == list and len(function_result) > 0 and isinstance(function_result[0], ResponseFuture):
            self._new_futures = function_result
            self._set_state(JobState.futures)
            self.invoke_status['status_done_timestamp'] = self.invoke_status['download_output_timestamp']
            del self.invoke_status['download_output_timestamp']
            return self._new_futures

        else:
            self._return_val = function_result
            self._set_state(JobState.success)
            return self._return_val
