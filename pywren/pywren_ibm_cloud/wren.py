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

import os
import sys
import enum
import json
import signal
import logging
import pywren_ibm_cloud.invokers as invokers
import pywren_ibm_cloud.wrenconfig as wrenconfig
from pywren_ibm_cloud.wrenutil import generate_pywren_id_msg, split_pywren_id
from pywren_ibm_cloud import wrenlogging
from pywren_ibm_cloud.storage import storage
from pywren_ibm_cloud.executor import Executor
from pywren_ibm_cloud.wait import wait, ALL_COMPLETED
from pywren_ibm_cloud.wrenutil import timeout_handler
from pywren_ibm_cloud.storage.cleaner import clean_os_bucket
from pywren_ibm_cloud.future import ResponseFuture, JobState

logger = logging.getLogger(__name__)


class ExecutorState(enum.Enum):
    new = 1
    finished = 2
    error = 3


class ibm_cf_executor:

    def __init__(self, config=None, runtime=None, log_level=None, runtime_timeout=wrenconfig.CF_RUNTIME_TIMEOUT):
        """
        Initialize and return an executor class.

        :param config: Settings passed in here will override those in `pywren_config`. Default None.
        :param runtime: Runtime name to use. Default None.
        :param runtime_timeout: Max time per action. Default 600
        :return `executor` object.

        Usage
          >>> import pywren_ibm_cloud as pywren
          >>> pw = pywren.ibm_cf_executor()
        """
        self._state = ExecutorState.new

        if config is None:
            self.config = wrenconfig.default()
        else:
            self.config = wrenconfig.default(config)

        if runtime:
            self.config['ibm_cf']['action_name'] = runtime

        if log_level:
            wrenlogging.default_config(log_level)

        ibm_cf_config = self.config['ibm_cf']
        self.runtime = ibm_cf_config['action_name']
        self.cf_cluster = ibm_cf_config['is_cf_cluster']
        self.data_cleaner = self.config['pywren']['data_cleaner']

        retry_config = {}
        retry_config['invocation_retry'] = self.config['pywren']['invocation_retry']
        retry_config['retry_sleeps'] = self.config['pywren']['retry_sleeps']
        retry_config['retries'] = self.config['pywren']['retries']

        invoker = invokers.IBMCloudFunctionsInvoker(ibm_cf_config, retry_config)

        self.storage_config = wrenconfig.extract_storage_config(self.config)
        self.internal_storage = storage.InternalStorage(self.storage_config)
        self.executor = Executor(invoker, self.config, self.internal_storage, runtime_timeout)
        self.executor_id = self.executor.executor_id

        self.futures = []
        self.reduce_future = None

    def call_async(self, func, data, extra_env=None, extra_meta=None):
        """
        For run one function execution
        :param func: the function to map over the data
        :param data: input data
        :param extra_env: Additional environment variables for action environment. Default None.
        :param extra_meta: Additional metadata to pass to action. Default None.

        Usage
          >>> import pywren_ibm_cloud as pywren
          >>> pw = pywren.ibm_cf_executor()
          >>> future = pw.call_async(foo, data)
        """
        if self._state == ExecutorState.finished or self._state == ExecutorState.error:
            raise Exception('You cannot run pw.call_async() in the current state,'
                            ' create a new pywren.ibm_cf_executor() instance.')

        future = self.executor.single_call(func, data, extra_env, extra_meta)[0]
        self.futures.append(future)

        callgroup_id = future.callgroup_id
        msg = generate_pywren_id_msg(self.executor_id, callgroup_id)
        logger.debug(msg)
        if(logger.getEffectiveLevel() == logging.WARNING):
            print(msg)

        return future

    def map(self, map_function, map_iterdata, extra_env=None, extra_meta=None,
            remote_invocation=False, invoke_pool_threads=10, data_all_as_one=True,
            overwrite_invoke_args=None, exclude_modules=None):
        """
        :param func: the function to map over the data
        :param iterdata: An iterable of input data
        :param extra_env: Additional environment variables for action environment. Default None.
        :param extra_meta: Additional metadata to pass to action. Default None.
        :param invoke_pool_threads: Number of threads to use to invoke.
        :param data_all_as_one: upload the data as a single object. Default True
        :param overwrite_invoke_args: Overwrite other args. Mainly used for testing.
        :param exclude_modules: Explicitly keep these modules from pickled dependencies.
        :return: A list with size `len(iterdata)` of futures for each job
        :rtype: list of futures.

        Usage
          >>> import pywren_ibm_cloud as pywren
          >>> pw = pywren.ibm_cf_executor()
          >>> futures = pw.map(foo, data_list)
        """
        if self._state == ExecutorState.finished or self._state == ExecutorState.error:
            raise Exception('You cannot run pw.map() in the current state.'
                            ' Create a new pywren.ibm_cf_executor() instance.')

        futures = self.executor.multiple_call(map_function=map_function,
                                              iterdata=map_iterdata,
                                              extra_env=extra_env,
                                              extra_meta=extra_meta,
                                              remote_invocation=remote_invocation,
                                              invoke_pool_threads=invoke_pool_threads,
                                              data_all_as_one=data_all_as_one,
                                              overwrite_invoke_args=overwrite_invoke_args,
                                              exclude_modules=exclude_modules)
        self.futures.extend(futures)

        callgroup_id = futures[0].callgroup_id
        msg = generate_pywren_id_msg(self.executor_id, callgroup_id)
        logger.debug(msg)
        if(logger.getEffectiveLevel() == logging.WARNING):
            print(msg)

        if len(futures) == 1:
            return futures[0]
        return futures

    def map_reduce(self, map_function, map_iterdata, reduce_function, chunk_size=None,
                   extra_env=None, extra_meta=None, remote_invocation=False,
                   reducer_one_per_object=False, reducer_wait_local=True,
                   invoke_pool_threads=10, data_all_as_one=True,
                   overwrite_invoke_args=None, exclude_modules=None):
        """
        Map the map_function over the data and apply the reduce_function across all futures.
        This method is executed all within CF.
        :param map_function: the function to map over the data
        :param map_iterdata:  the function to reduce over the futures
        :param reduce_function:  the function to reduce over the futures
        :param chunk_size: the size of the data chunks. 'None' for processing the whole file in one map
        :param extra_env: Additional environment variables for action environment. Default None.
        :param extra_meta: Additional metadata to pass to action. Default None.
        :param reducer_one_per_object: Set one reducer per object after running the partitioner
        :param reducer_wait_local: Wait for results locally
        :param invoke_pool_threads: Number of threads to use to invoke.
        :param data_all_as_one: upload the data as a single object. Default True
        :param overwrite_invoke_args: Overwrite other args. Mainly used for testing.
        :param exclude_modules: Explicitly keep these modules from pickled dependencies.
        :return: A list with size `len(map_iterdata)` of futures for each job

        Usage
          >>> import pywren_ibm_cloud as pywren
          >>> pw = pywren.ibm_cf_executor()
          >>> pw.map_reduce(foo, map_data_list, bar)
        """

        if self._state == ExecutorState.finished or self._state == ExecutorState.error:
            raise Exception('You cannot run pw.map_reduce() in the current state.'
                            ' Create a new pywren.ibm_cf_executor() instance.')

        futures = self.executor.multiple_call(map_function, map_iterdata,
                                              reduce_function=reduce_function,
                                              obj_chunk_size=chunk_size,
                                              extra_env=extra_env,
                                              extra_meta=extra_meta,
                                              remote_invocation=remote_invocation,
                                              invoke_pool_threads=invoke_pool_threads,
                                              data_all_as_one=data_all_as_one,
                                              overwrite_invoke_args=overwrite_invoke_args,
                                              exclude_modules=exclude_modules,
                                              reducer_one_per_object=reducer_one_per_object,
                                              reducer_wait_local=reducer_wait_local)
        self.futures.extend(futures)

        callgroup_id = futures[0].callgroup_id
        msg = generate_pywren_id_msg(self.executor_id, callgroup_id)
        logger.debug(msg)
        if(logger.getEffectiveLevel() == logging.WARNING):
            print(msg)

        if len(futures) == 1:
            return futures[0]
        return futures

    def wait(self, futures=None, throw_except=True, return_when=ALL_COMPLETED,
             THREADPOOL_SIZE=16, WAIT_DUR_SEC=2):
        """
        Wait for the Future instances `fs` to complete. Returns a 2-tuple of
        lists. The first list contains the futures that completed
        (finished or cancelled) before the wait completed. The second
        contains uncompleted futures.

        :param return_when: One of `ALL_COMPLETED`, `ANY_COMPLETED`, `ALWAYS`
        :param THREADPOOL_SIZE: Number of threads to use. Default 64
        :param WAIT_DUR_SEC: Time interval between each check.
        :return: `(fs_dones, fs_notdones)`
            where `fs_dones` is a list of futures that have completed
            and `fs_notdones` is a list of futures that have not completed.
        :rtype: 2-tuple of lists

        Usage
          >>> import pywren_ibm_cloud as pywren
          >>> pw = pywren.ibm_cf_executor()
          >>> pw.map(foo, data_list)
          >>> dones, not_dones = pw.wait()
          >>> # not_dones should be an empty list.
          >>> results = [f.result() for f in dones]
        """
        if not futures:
            futures = self.futures

        if not futures:
            raise Exception('No activations to track. You must run pw.call_async(),'
                            ' pw.map() or pw.map_reduce() before call pw.wait()')

        return wait(futures, self.executor_id, self.internal_storage, throw_except=throw_except,
                    return_when=return_when, THREADPOOL_SIZE=THREADPOOL_SIZE, WAIT_DUR_SEC=WAIT_DUR_SEC)

    def get_result(self, futures=None, pywren_id=None, throw_except=True, timeout=wrenconfig.CF_RUNTIME_TIMEOUT,
                   THREADPOOL_SIZE=64, WAIT_DUR_SEC=2, get_status=False):
        """
        For getting PyWren results
        :param futures: Futures list. Default None
        :param invoke_id: an Invocation ID from PyWren for getting result from remote. Default None
        :param throw_except: Reraise exception if call raised. Default True.
        :param verbose: Shows some information prints. Default False
        :param timeout: Timeout for waiting results.
        :param THREADPOOL_SIZE: Number of threads to use. Default 64
        :param get_status: define True to get a tuple of results and statuses. Default False
        :return: The result of the future/s

        Usage
          >>> import pywren_ibm_cloud as pywren
          >>> pw = pywren.ibm_cf_executor()
          >>> pw.map(foo, data)
          >>> result = pw.get_result()
        """
        get_result_from_id = False
        if futures:
            # Ensure futures is a list
            if type(futures) != list:
                ftrs = [futures]
            else:
                ftrs = futures
        elif pywren_id:
            get_result_from_id = True
            executor_id, callgroup_id = split_pywren_id(pywren_id)
            calls_ids = self.internal_storage.get_calls_ids(executor_id, callgroup_id)
            ftrs = []
            for call_id in calls_ids:
                f = ResponseFuture(call_id, callgroup_id, executor_id, '', {}, self.storage_config)
                f._state = JobState.invoked
                ftrs.append(f)
        else:
            # In this case self.futures is always a list
            ftrs = self.futures

        if not ftrs and not get_result_from_id:
            raise Exception('You must run pw.call_async(), pw.map()'
                            ' or pw.map_reduce() before call pw.get_result()')

        if get_result_from_id:
            msg = 'Executor ID {} Getting results from PyWren ID: {}'.format(self.executor_id, pywren_id)
        else:
            msg = 'Executor ID {} Getting results'.format(self.executor_id)

        logger.debug(msg)
        if(logger.getEffectiveLevel() == logging.WARNING):
            print(msg)

        pbar = None
        if not get_result_from_id:

            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout)

            if not self.cf_cluster and logger.getEffectiveLevel() == logging.WARNING:
                import tqdm
                print()
                pbar = tqdm.tqdm(bar_format='  {l_bar}{bar}| {n_fmt}/{total_fmt}  ',
                                 total=len(ftrs), disable=False)

        result = None
        try:
            wait(ftrs, self.executor_id, self.internal_storage, throw_except=throw_except,
                 THREADPOOL_SIZE=THREADPOOL_SIZE, WAIT_DUR_SEC=WAIT_DUR_SEC, pbar=pbar)
            result = [f.result(throw_except=throw_except) for f in ftrs if f.done and not f.futures]

        except TimeoutError:
            if pbar:
                pbar.close()
                print()
            not_dones_activation_ids = set([f.activation_id for f in ftrs if not f.done])
            msg = ('Executor ID {} Raised timeout of {} seconds getting results '
                   '\nActivations not done: {}'.format(self.executor_id, timeout, not_dones_activation_ids))
            logger.debug(msg)
            if(logger.getEffectiveLevel() == logging.WARNING):
                print(msg)
            self._state = ExecutorState.error
            result = None

        except KeyboardInterrupt:
            if pbar:
                pbar.close()
                print()
            not_dones_activation_ids = [f.activation_id for f in ftrs if not f.done]
            msg = 'Executor ID {} Cancelled  \nActivations not done: {}'.format(self.executor_id, not_dones_activation_ids)
            logger.debug(msg)
            if(logger.getEffectiveLevel() == logging.WARNING):
                print(msg)
            if self.data_cleaner and not self.cf_cluster:
                self.clean()
            exit()

        finally:
            signal.alarm(0)
            if pbar:
                pbar.close()
                print()
            if self.data_cleaner and not self.cf_cluster:
                self.clean()

        msg = "Executor ID {} Finished\n".format(self.executor_id)
        logger.debug(msg)
        if(logger.getEffectiveLevel() == logging.WARNING and self.data_cleaner):
            print(msg)

        statuses = [f.run_status for f in ftrs]

        if result is not None:
            if len(result) == 0:
                log_msg = 'Executor ID {} Invocations with PyWren ID: {} havn\'t done yet'.format(self.executor_id, pywren_id)
                logger.warning(log_msg)
                if get_status:
                    return None, None
                return
            elif len(result) == 1:
                if get_status:
                    return result[0], statuses[0]
                return result[0]

        if get_status:
            return result, statuses
        return result

    def create_timeline_plots(self, dst, name, run_statuses=None, invoke_statuses=None):
        """
        Creates timeline and histogram of the current execution in dst.

        :param dst: destination folder to save .png plots.
        :param name: name of the file.
        :param run_statuses: run statuses timestamps.
        :param invoke_statuses: invocation statuses timestamps.
        """
        from pywren_ibm_cloud.plots import create_timeline, create_histogram

        if self.futures and not run_statuses and not invoke_statuses:
            run_statuses = [f.run_status for f in self.futures]
            invoke_statuses = [f.invoke_status for f in self.futures]

        if not run_statuses and not invoke_statuses:
            raise Exception('You must provide run_statuses and invoke_statuses')

        create_timeline(dst, name, run_statuses, invoke_statuses)
        create_histogram(dst, name, run_statuses, x_lim=150)

    def clean(self, local_execution=True):
        """
        Deletes all the files from COS. These files include the function,
        the data serialization and the function invocation results.
        """
        storage_bucket = self.storage_config['storage_bucket']
        storage_prerix = self.storage_config['storage_prefix']
        storage_prerix = os.path.join(storage_prerix, self.executor_id)

        msg = ("Executor ID {} Cleaning partial results from bucket '{}' "
               "and prefix '{}'".format(self.executor_id, storage_bucket, storage_prerix))
        logger.debug(msg)
        if(logger.getEffectiveLevel() == logging.WARNING):
            print(msg)
            if not self.data_cleaner:
                print()

        if local_execution:
            # 1st case: Not background. The main code waits until the cleaner finishes its execution.
            # It is not ideal for performance tests, since it can take long time to complete.
            #clean_os_bucket(storage_bucket, storage_prerix, self.internal_storage)

            # 2nd case: Execute in Background as a subprocess. The main program does not wait for its completion.
            storage_config = json.dumps(self.internal_storage.get_storage_config())
            storage_config = storage_config.replace('"', '\\"')

            cmdstr = ("{} -c 'from pywren_ibm_cloud.storage.cleaner import clean_bucket; \
                              clean_bucket(\"{}\", \"{}\", \"{}\")'".format(sys.executable,
                                                                            storage_bucket,
                                                                            storage_prerix,
                                                                            storage_config))
            os.popen(cmdstr)

        else:
            extra_env = {'STORE_STATUS': False,
                         'STORE_RESULT': False}
            sys.stdout = open(os.devnull, 'w')
            self.executor.call_async(clean_os_bucket, [storage_bucket, storage_prerix], extra_env=extra_env)
            sys.stdout = sys.__stdout__
