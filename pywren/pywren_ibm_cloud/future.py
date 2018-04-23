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

import logging
import time
import enum
from six import reraise
from six.moves import cPickle as pickle
from pywren_ibm_cloud.storage import storage, storage_utils

try:
    from tblib import pickling_support
except:
    from pywren_ibm_cloud.libs.tblib import pickling_support

pickling_support.install()

logger = logging.getLogger(__name__)


class JobState(enum.Enum):
    new = 1
    invoked = 2
    running = 3
    redirected = 4
    success = 5
    error = 6


class ResponseFuture(object):

    """
    Object representing the result of a PyWren invocation. Returns the status of the
    execution and the result when available.
    """
    GET_RESULT_SLEEP_SECS = 4
    def __init__(self, call_id, callgroup_id, executor_id, activation_id, invoke_metadata, storage_config):
        self.call_id = call_id
        self.callgroup_id = callgroup_id
        self.executor_id = executor_id
        self.activation_id = activation_id

        self.storage_config = storage_config

        self._state = JobState.new
        self._exception = Exception()
        self._return_val = None
        self._traceback = None
        self._call_invoker_result = None
        self._invoke_metadata = invoke_metadata.copy()

        self.redirections = []  # Will contain previous invocations data in case of redirection
        self.run_status = None
        self.invoke_status = None

        self.status_query_count = 0
        self.output_query_count = 0

        self.storage_path = storage_utils.get_storage_path(self.storage_config)

    def _set_state(self, new_state):
        ## FIXME add state machine
        self._state = new_state

    def cancel(self):
        raise NotImplementedError("Cannot cancel dispatched jobs")

    def cancelled(self):
        raise NotImplementedError("Cannot cancel dispatched jobs")

    @property
    def redirected(self):
        """
        The response of a call was a FutureResponse instance. 
        It has to wait to the new invocation output.
        """
        return self._state == JobState.redirected

    def running(self):
        raise NotImplementedError()

    @property
    def done(self):
        if self._state in [JobState.success, JobState.error]:
            return True
        return False

    def result(self, check_only=False, throw_except=True, verbose=False, storage_handler=None):
        """
        Return the value returned by the call.
        If the call raised an exception, this method will raise the same exception
        If the future is cancelled before completing then CancelledError will be raised.

        :param timeout: This method will wait up to timeout seconds before raising
            a TimeoutError if function hasn't completed. If None, wait indefinitely. Default None.
        :param check_only: Return None immediately if job is not complete. Default False.
        :param throw_except: Reraise exception if call raised. Default true.
        :param verbose: Shows some information prints.
        :param storage_handler: Storage handler to poll cloud storage. Default None.
        :return: Result of the call.
        :raises CancelledError: If the job is cancelled before completed.
        :raises TimeoutError: If job is not complete after `timeout` seconds.
        """
        if self._state == JobState.new:
            raise ValueError("job not yet invoked")

        if self._state == JobState.success:
            return self._return_val

        if self._state == JobState.error:
            if throw_except:
                raise self._exception
            else:
                return None

        if storage_handler is None:
            storage_handler = storage.Storage(self.storage_config)
 
        storage_utils.check_storage_path(storage_handler.get_storage_config(), self.storage_path)
        call_status = storage_handler.get_call_status(self.executor_id, self.callgroup_id, self.call_id)
        self.status_query_count += 1

        if check_only is True:
            if call_status is None:
                return None

        if self._state == JobState.redirected and call_status is None:
            return None

        while call_status is None:
            time.sleep(self.GET_RESULT_SLEEP_SECS)
            call_status = storage_handler.get_call_status(self.executor_id, self.callgroup_id, self.call_id)
            self.status_query_count += 1

        self._invoke_metadata['status_done_timestamp'] = time.time()
        self._invoke_metadata['status_query_count'] = self.status_query_count

        self.run_status = call_status # this is the remote status information
        self.invoke_status = self._invoke_metadata # local status information

        if not self.redirections:
            #First execution
            self.start_time = call_status['start_time']
        total_time = round(call_status['end_time'] - self.start_time, 2)

        if call_status['exception'] is not None:
            # the wrenhandler had an exception
            self._set_state(JobState.error)
            exception_str = call_status['exception']
            exception_args = call_status['exception_args']

            log_msg = 'Executor ID {} Error in {} {} - Time: {} seconds- Result: {}'.format(self.executor_id,
                                                                                            self.call_id,
                                                                                            self.activation_id,
                       str(total_time), exception_args[0]+" "+exception_args[1])
            logger.info(log_msg)
            if verbose and logger.getEffectiveLevel() == logging.WARNING:
                print(log_msg)

            if exception_args[0] == "WRONGVERSION":
                if throw_except:
                    raise Exception("Pywren version mismatch: remote " + \
                        "expected version {}, local library is version {}".format(
                            exception_args[2], exception_args[3]))
                return None
            elif exception_args[0] == "OUTATIME":
                if throw_except:
                    raise Exception("process ran out of time - {} - {}".format(self.call_id,
                                                                               self.activation_id))
                return None
            else:
                if 'exception_traceback' in call_status:
                    self._exception = Exception(exception_str, *exception_args)
                if throw_except:
                    raise self._exception
                return None

        call_output_time = time.time()
        call_invoker_result = storage_handler.get_call_output(self.executor_id, self.callgroup_id, self.call_id)
        self.output_query_count += 1

        while call_invoker_result is None and self.output_query_count < 5:
            time.sleep(self.GET_RESULT_SLEEP_SECS)
            call_invoker_result = storage_handler.get_call_output(self.executor_id, self.callgroup_id, self.call_id)
            self.output_query_count += 1
            
        if call_invoker_result == None:
            if throw_except:
                raise Exception('Unable to get the output of the function - Activation ID: {}'.format(self.activation_id))
            else:
                self._set_state(JobState.error)
                return None
            
        call_invoker_result = pickle.loads(call_invoker_result)
        call_output_time_done = time.time()
        self._call_invoker_result = call_invoker_result     

        self._invoke_metadata['download_output_time'] = call_output_time_done - call_output_time
        self._invoke_metadata['output_query_count'] = self.output_query_count
        self._invoke_metadata['download_output_timestamp'] = call_output_time_done
        call_success = call_invoker_result['success'] 
        self.invoke_status = self._invoke_metadata # local status information

        if call_success:
            function_result = call_invoker_result['result']
            if isinstance(function_result, ResponseFuture):

                old_data = {'executor_id' : self.executor_id,
                            'callgroup_id' : self.callgroup_id,
                            'call_id' : self.call_id, 
                            'activation_id' : self.activation_id,
                            'call_status': call_status,
                            'invoke_status': self.invoke_status}

                self.redirections.append(old_data)

                self.executor_id = function_result.executor_id
                self.callgroup_id = function_result.callgroup_id
                self.call_id = function_result.call_id
                self.activation_id = function_result.activation_id
                self._invoke_metadata = function_result._invoke_metadata
                
                self._set_state(JobState.redirected)
                
                return None
            
            if self.redirections:
                original_call_id = self.redirections[0]['call_id']
                original_activation_id = self.redirections[0]['activation_id']
            else:
                original_call_id = self.call_id
                original_activation_id = self.activation_id
            
            log_msg= "Executor ID {} Response from Function {} - Activation ID: {} - Time: {} seconds".format(self.executor_id,
                                                                                                      original_call_id,
                                                                                                      original_activation_id,
                                                                                                      str(total_time))
            logger.info(log_msg)
            if verbose and logger.getEffectiveLevel() == logging.WARNING:
                print(log_msg)

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
                logging.warning(
                    "there was an error pickling. The original exception: " + \
                        "{}\nThe pickling exception: {}".format(
                            call_invoker_result['exc_value'],
                            str(call_invoker_result['pickle_exception'])))

                reraise(Exception, call_invoker_result['exc_value'],
                        call_invoker_result['exc_traceback'])
            else:
                # reraise the exception
                reraise(*self._traceback)
        else:
            self._set_state(JobState.error)
            return None  # nothing, don't raise, no value
