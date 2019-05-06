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
import time
import enum
import json
import signal
import logging
from pywren_ibm_cloud import invokers
from pywren_ibm_cloud import wrenconfig
from pywren_ibm_cloud import wrenlogging
from pywren_ibm_cloud.storage import storage
from pywren_ibm_cloud.executor import Executor
from pywren_ibm_cloud.wait import wait, ALL_COMPLETED
from pywren_ibm_cloud.utils import timeout_handler, is_notebook, is_unix_system, is_cf_cluster, create_ri_action_name
from pywren_ibm_cloud.storage.cleaner import clean_os_bucket

logger = logging.getLogger(__name__)


class ExecutorState(enum.Enum):
    new = 1
    running = 2
    ready = 3
    success = 4
    error = 5
    finished = 6


class ibm_cf_executor:

    def __init__(self, config=None, runtime=None, runtime_memory=None, log_level=None, rabbitmq_monitor=False):
        """
        Initialize and return an executor class.

        :param config: Settings passed in here will override those in `pywren_config`. Default None.
        :param runtime: Runtime name to use. Default None.
        :param runtime_memory: memory to use in the runtime
        :param log_level: log level to use during the execution
        :param rabbitmq_monitor: use rabbitmq as monitoring system
        :return `executor` object.

        Usage
          >>> import pywren_ibm_cloud as pywren
          >>> pw = pywren.ibm_cf_executor()
        """
        self.start_time = time.time()
        self._state = ExecutorState.new

        if config is None:
            self.config = wrenconfig.default()
        else:
            self.config = wrenconfig.default(config)

        self.is_cf_cluster = is_cf_cluster()
        self.data_cleaner = self.config['pywren']['data_cleaner']

        # Overwrite runtime variables
        if runtime:
            self.config['pywren']['runtime'] = runtime
        if runtime_memory:
            self.config['pywren']['runtime_memory'] = int(runtime_memory)

        # Log level Configuration
        self.log_level = log_level
        if not self.log_level:
            if(logger.getEffectiveLevel() != logging.WARNING):
                self.log_level = logging.getLevelName(logger.getEffectiveLevel())
        if self.log_level:
            os.environ["PYWREN_LOG_LEVEL"] = self.log_level
            if not self.is_cf_cluster:
                wrenlogging.default_config(self.log_level)

        # RabbitMQ monitor configuration
        self.rabbitmq_monitor = rabbitmq_monitor
        if self.rabbitmq_monitor:
            if self.config['rabbitmq']['amqp_url']:
                os.environ["PYWREN_RABBITMQ_MONITOR"] = 'True'
            else:
                self.rabbitmq_monitor = False
        else:
            self.config['rabbitmq']['amqp_url'] = None

        storage_config = wrenconfig.extract_storage_config(self.config)
        self.internal_storage = storage.InternalStorage(storage_config)

        invoker = invokers.IBMCloudFunctionsInvoker(self.config)
        self.executor = Executor(invoker, self.config, self.internal_storage)
        self.executor_id = self.executor.executor_id

        self.futures = []

    def call_async(self, func, data, extra_env=None, extra_meta=None, timeout=wrenconfig.RUNTIME_TIMEOUT):
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
        if self._state == ExecutorState.finished:
            raise Exception('You cannot run pw.call_async() in the current state,'
                            ' create a new pywren.ibm_cf_executor() instance.')

        future = self.executor.call_async(func, data, extra_env, extra_meta, timeout)[0]
        self.futures.append(future)
        self._state = ExecutorState.running

        return future

    def map(self, map_function, map_iterdata, extra_env=None, extra_meta=None,
            chunk_size=None, remote_invocation=False, timeout=wrenconfig.RUNTIME_TIMEOUT,
            remote_invocation_groups=None, invoke_pool_threads=500,
            data_all_as_one=True, overwrite_invoke_args=None, exclude_modules=None):
        """
        :param func: the function to map over the data
        :param iterdata: An iterable of input data
        :param extra_env: Additional environment variables for action environment. Default None.
        :param extra_meta: Additional metadata to pass to action. Default None.
        :param chunk_size: the size of the data chunks. 'None' for processing the whole file in one map
        :param data_type: the type of the data. Now allowed: None (files with newline) and csv.
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
        if self._state == ExecutorState.finished:
            raise Exception('You cannot run pw.map() in the current state.'
                            ' Create a new pywren.ibm_cf_executor() instance.')

        inv_action_name = self.executor.invoker.action_name
        if len(map_iterdata) == 1 or self.is_cf_cluster:
            # Ensure no remote invocation in these particular cases
            remote_invocation = False

        if remote_invocation:
            ria_memory = wrenconfig.RUNTIME_RI_MEMORY_DEFAULT
            self.executor.invoker.action_name = create_ri_action_name(inv_action_name, ria_memory)

        map_futures, unused_ppo = self.executor.map(map_function=map_function,
                                                    iterdata=map_iterdata,
                                                    obj_chunk_size=chunk_size,
                                                    extra_env=extra_env,
                                                    extra_meta=extra_meta,
                                                    remote_invocation=remote_invocation,
                                                    remote_invocation_groups=remote_invocation_groups,
                                                    invoke_pool_threads=invoke_pool_threads,
                                                    data_all_as_one=data_all_as_one,
                                                    overwrite_invoke_args=overwrite_invoke_args,
                                                    exclude_modules=exclude_modules,
                                                    job_max_runtime=timeout)
        self.futures.extend(map_futures)
        self.executor.invoker.action_name = inv_action_name
        self._state = ExecutorState.running

        if len(map_futures) == 1:
            return map_futures[0]
        return map_futures

    def map_reduce(self, map_function, map_iterdata, reduce_function, extra_env=None,
                   extra_meta=None, chunk_size=None, remote_invocation=False,
                   remote_invocation_groups=None, timeout=wrenconfig.RUNTIME_TIMEOUT,
                   reducer_one_per_object=False, reducer_wait_local=False,
                   invoke_pool_threads=500, data_all_as_one=True, overwrite_invoke_args=None,
                   exclude_modules=None):
        """
        Map the map_function over the data and apply the reduce_function across all futures.
        This method is executed all within CF.
        :param map_function: the function to map over the data
        :param map_iterdata:  the function to reduce over the futures
        :param reduce_function:  the function to reduce over the futures
        :param extra_env: Additional environment variables for action environment. Default None.
        :param extra_meta: Additional metadata to pass to action. Default None.
        :param chunk_size: the size of the data chunks. 'None' for processing the whole file in one map
        :param data_type: the type of the data. Now allowed: None (files with newline) and csv.
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

        if self._state == ExecutorState.finished:
            raise Exception('You cannot run pw.map_reduce() in the current state.'
                            ' Create a new pywren.ibm_cf_executor() instance.')

        inv_action_name = self.executor.invoker.action_name

        if len(map_iterdata) == 1 or self.is_cf_cluster:
            # Ensure no remote invocation in these particular cases
            remote_invocation = False

        if remote_invocation:
            ria_memory = wrenconfig.RUNTIME_RI_MEMORY_DEFAULT
            self.executor.invoker.action_name = create_ri_action_name(inv_action_name, ria_memory)

        map_futures, parts_per_object = self.executor.map(map_function, map_iterdata,
                                                          extra_env=extra_env,
                                                          extra_meta=extra_meta,
                                                          obj_chunk_size=chunk_size,
                                                          remote_invocation=remote_invocation,
                                                          remote_invocation_groups=remote_invocation_groups,
                                                          invoke_pool_threads=invoke_pool_threads,
                                                          data_all_as_one=data_all_as_one,
                                                          overwrite_invoke_args=overwrite_invoke_args,
                                                          exclude_modules=exclude_modules,
                                                          job_max_runtime=timeout)

        self._state = ExecutorState.running
        if reducer_wait_local:
            self.monitor(futures=map_futures)

        self.executor.invoker.action_name = inv_action_name
        futures = self.executor.reduce(reduce_function, map_futures, parts_per_object,
                                       reducer_one_per_object, extra_env, extra_meta)
        self.futures.extend(futures)

        if len(futures) == 1:
            return futures[0]
        return futures

    def monitor(self, futures=None, throw_except=True, return_when=ALL_COMPLETED,
                download_results=False, timeout=wrenconfig.RUNTIME_TIMEOUT,
                THREADPOOL_SIZE=128, WAIT_DUR_SEC=1):
        """
        Wait for the Future instances `fs` to complete. Returns a 2-tuple of
        lists. The first list contains the futures that completed
        (finished or cancelled) before the wait completed. The second
        contains uncompleted futures.
        :param futures: Futures list. Default None
        :param throw_except: Re-raise exception if call raised. Default True.
        :param return_when: One of `ALL_COMPLETED`, `ANY_COMPLETED`, `ALWAYS`
        :param download_results: Download results. Default false (Only download statuses)
        :param timeout: Timeout of waiting for results.
        :param THREADPOOL_SIZE: Number of threads to use. Default 64
        :param WAIT_DUR_SEC: Time interval between each check.
        :return: `(fs_done, fs_notdone)`
            where `fs_done` is a list of futures that have completed
            and `fs_notdone` is a list of futures that have not completed.
        :rtype: 2-tuple of lists

        Usage
          >>> import pywren_ibm_cloud as pywren
          >>> pw = pywren.ibm_cf_executor()
          >>> pw.map(foo, data_list)
          >>> dones, not_dones = pw.monitor()
          >>> # not_dones should be an empty list.
          >>> results = [f.result() for f in dones]
        """
        if futures:
            # Ensure futures is a list
            if type(futures) != list:
                ftrs = [futures]
            else:
                ftrs = futures
        else:
            # In this case self.futures is always a list
            ftrs = self.futures

        if not ftrs:
            raise Exception('You must run pw.call_async(), pw.map()'
                            ' or pw.map_reduce() before call pw.get_result()')

        rabbit_amqp_url = None
        if self._state == ExecutorState.running:
            if self.rabbitmq_monitor:
                rabbit_amqp_url = self.config['rabbitmq'].get('amqp_url')
            if rabbit_amqp_url and not download_results:
                logger.info('Going to use RabbitMQ to monitor function activations')
            if download_results:
                msg = 'Executor ID {} Getting results...'.format(self.executor_id)
            else:
                msg = 'Executor ID {} Waiting for functions to complete...'.format(self.executor_id)
            logger.info(msg)
            if not self.log_level and self._state == ExecutorState.running:
                print(msg)

        if is_unix_system():
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout)

        pbar = None
        if not self.is_cf_cluster and self._state == ExecutorState.running \
           and not self.log_level and not is_notebook():
            import tqdm
            print()
            pbar = tqdm.tqdm(bar_format='  {l_bar}{bar}| {n_fmt}/{total_fmt}  ',
                             total=len(ftrs), disable=False)

        try:
            wait(ftrs, self.executor_id, self.internal_storage, download_results=download_results,
                 throw_except=throw_except, return_when=return_when, rabbit_amqp_url=rabbit_amqp_url,
                 pbar=pbar, THREADPOOL_SIZE=THREADPOOL_SIZE, WAIT_DUR_SEC=WAIT_DUR_SEC)

        except TimeoutError:
            if download_results:
                not_dones_activation_ids = [f.activation_id for f in ftrs if not f.done]
            else:
                not_dones_activation_ids = [f.activation_id for f in ftrs if not f.ready]
            msg = ('Executor ID {} Raised timeout of {} seconds waiting for results '
                   '\nActivations not done: {}'.format(self.executor_id, timeout, not_dones_activation_ids))
            self._state = ExecutorState.error

        except KeyboardInterrupt:
            if download_results:
                not_dones_activation_ids = [f.activation_id for f in ftrs if not f.done]
            else:
                not_dones_activation_ids = [f.activation_id for f in ftrs if not f.ready]
            msg = 'Executor ID {} Cancelled  \nActivations not done: {}'.format(self.executor_id, not_dones_activation_ids)
            self._state = ExecutorState.error

        finally:
            if is_unix_system():
                signal.alarm(0)
            if pbar:
                pbar.close()
                print()
            if self._state == ExecutorState.error:
                logger.info(msg)
                if not self.log_level:
                    print(msg)
            if self.data_cleaner and not self.is_cf_cluster and self._state != ExecutorState.ready:
                self.clean()

        if download_results:
            fs_dones = [f for f in ftrs if f.done]
            fs_notdones = [f for f in ftrs if not f.done]
        else:
            fs_dones = [f for f in ftrs if f.ready]
            fs_notdones = [f for f in ftrs if not f.ready]

        self._state = ExecutorState.ready

        return fs_dones, fs_notdones

    def get_result(self, futures=None, throw_except=True, timeout=wrenconfig.RUNTIME_TIMEOUT,
                   THREADPOOL_SIZE=64, WAIT_DUR_SEC=1):
        """
        For getting PyWren results
        :param futures: Futures list. Default None
        :param throw_except: Reraise exception if call raised. Default True.
        :param verbose: Shows some information prints. Default False
        :param timeout: Timeout for waiting for results.
        :param THREADPOOL_SIZE: Number of threads to use. Default 64
        :param WAIT_DUR_SEC: Time interval between each check.
        :return: The result of the future/s

        Usage
          >>> import pywren_ibm_cloud as pywren
          >>> pw = pywren.ibm_cf_executor()
          >>> pw.map(foo, data)
          >>> results = pw.get_result()
        """
        fs_dones, unused_fs_notdones = self.monitor(futures=futures, throw_except=throw_except,
                                                    timeout=timeout, download_results=True,
                                                    THREADPOOL_SIZE=THREADPOOL_SIZE,
                                                    WAIT_DUR_SEC=WAIT_DUR_SEC)
        result = [f.result() for f in fs_dones if f.done and not f.futures]
        msg = "Executor ID {} Finished getting results".format(self.executor_id)
        logger.info(msg)
        if not self.log_level:
            print(msg)

        if result and len(result) == 1:
            return result[0]
        return result

    def create_timeline_plots(self, dst_dir, dst_file_name, futures=None):
        """
        Creates timeline and histogram of the current execution in dst.

        :param dst: destination folder to save .png plots.
        :param name: name of the file.
        :param run_statuses: run statuses timestamps.
        :param invoke_statuses: invocation statuses timestamps.
        """
        if futures:
            ftrs = futures
        else:
            ftrs = self.futures

        if not ftrs or self._state == ExecutorState.new:
            raise Exception('You must run pw.call_async(), pw.map() or pw.map_reduce()'
                            ' before call pw.create_timeline_plots()')

        logging.getLogger('matplotlib').setLevel(logging.WARNING)
        from pywren_ibm_cloud.plots import create_timeline, create_histogram

        msg = 'Executor ID {} Creating timeline plots'.format(self.executor_id)
        logger.info(msg)
        if not self.log_level:
            print(msg)
            if self.data_cleaner:
                print()

        if self.rabbitmq_monitor and not futures:
            ftrs_to_plot = self.futures
            self.monitor(futures=ftrs_to_plot)
        else:
            ftrs_to_plot = [f for f in ftrs if f.ready or f.done]

        if not ftrs_to_plot:
            return

        run_statuses = [f.run_status for f in ftrs_to_plot]
        invoke_statuses = [f.invoke_status for f in ftrs_to_plot]

        if self.rabbitmq_monitor and invoke_statuses:
            for in_stat in invoke_statuses:
                del in_stat['status_done_timestamp']

        create_timeline(dst_dir, dst_file_name, self.start_time, run_statuses, invoke_statuses, self.config['ibm_cos'])
        create_histogram(dst_dir, dst_file_name, self.start_time, run_statuses, self.config['ibm_cos'])

    def clean(self, local_execution=True):
        """
        Deletes all the files from COS. These files include the function,
        the data serialization and the function invocation results.
        """
        storage_bucket = self.config['pywren']['storage_bucket']
        storage_prerix = self.config['pywren']['storage_prefix']
        storage_prerix = os.path.join(storage_prerix, self.executor_id).replace("\\", "/")

        msg = "Executor ID {} Cleaning partial results from cos://{}/{}".format(self.executor_id,
                                                                                storage_bucket,
                                                                                storage_prerix)
        logger.info(msg)
        if not self.log_level:
            print(msg)
            if not self.data_cleaner:
                print()

        if local_execution:
            # 1st case: Not background. The main code waits until the cleaner finishes its execution.
            # It is not ideal for performance tests, since it can take long time to complete.
            # clean_os_bucket(storage_bucket, storage_prerix, self.internal_storage)

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

        self._state = ExecutorState.finished
