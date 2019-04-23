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
from six import reraise
from pywren_ibm_cloud.storage import storage, storage_utils
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


class ResponseFuture:

    """
    Object representing the result of a PyWren invocation. Returns the status of the
    execution and the result when available.
    """
    GET_RESULT_SLEEP_SECS = 1
    GET_RESULT_MAX_RETRIES = 10

    def __init__(self, call_id, callgroup_id, executor_id, activation_id, invoke_metadata, storage_config):
        self.call_id = call_id
        self.callgroup_id = callgroup_id
        self.executor_id = executor_id
        self.activation_id = activation_id

        self.storage_config = storage_config

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

        self.storage_path = storage_utils.get_storage_path(self.storage_config)

    def _set_state(self, new_state):
        # FIXME add state machine
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
        if self.ready or self.done:
            return self.run_status

        if internal_storage is None:
            internal_storage = storage.InternalStorage(self.storage_config)

        storage_utils.check_storage_path(internal_storage.get_storage_config(), self.storage_path)
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

        if call_status['exception'] is not None:
            # the wrenhandler had an exception
            self._set_state(JobState.error)
            exception_str = call_status['exception']
            exception_args = call_status['exception_args']

            log_msg = ('Executor ID {} Error in {} {} - Time: {} '
                       'seconds- Result: {}'.format(self.executor_id,
                                                    self.call_id,
                                                    self.activation_id,
                                                    str(total_time),
                                                    exception_args[0]+" "+exception_args[1]))
            logger.debug(log_msg)

            if exception_args[0] == "WRONGVERSION":
                if throw_except:
                    raise Exception("Pywren version mismatch: remote "
                                    "expected version {}, local library is version {}".format(
                                     exception_args[2], exception_args[3]))
                return None
            elif exception_args[0] == "OUTATIME":
                if throw_except:
                    raise Exception("Process ran out of time - {} - {}".format(self.call_id,
                                                                               self.activation_id))
                return None
            elif exception_args[0] == "OUTOFMEMORY":
                if throw_except:
                    raise Exception("Process exceeded maximum memory and was "
                                    "killed - {} - {}".format(self.call_id, self.activation_id))
                return None
            else:
                if 'exception_traceback' in call_status:
                    self._exception = Exception(exception_str, *exception_args)
                if throw_except:
                    raise self._exception
                return None

        log_msg = ('Executor ID {} Response from Function {} - Activation '
                   'ID: {} - Time: {} seconds'.format(self.executor_id,
                                                      self.call_id,
                                                      self.activation_id,
                                                      str(total_time)))
        logger.debug(log_msg)
        self._set_state(JobState.ready)

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

        if self._state == JobState.error:
            if throw_except:
                raise self._exception
            else:
                return None

        if internal_storage is None:
            internal_storage = storage.InternalStorage(self.storage_config)

        self.status(check_only, throw_except, internal_storage)

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

        call_success = call_invoker_result['success']

        if call_success:
            log_msg = ('Executor ID {} Got output from Function {} - Activation '
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

        elif throw_except:
            self._exception = call_invoker_result['result']
            self._traceback = (call_invoker_result['exc_type'],
                               call_invoker_result['exc_value'],
                               call_invoker_result['exc_traceback'])

            self._set_state(JobState.error)
            if call_invoker_result.get('pickle_fail', False):
                fault = Exception(call_invoker_result['exc_value'])
                reraise(Exception, fault, call_invoker_result['exc_traceback'])
            else:
                reraise(*self._traceback)
        else:
            self._set_state(JobState.error)
            return None  # nothing, don't raise, no value
