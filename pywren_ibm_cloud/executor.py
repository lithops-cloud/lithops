import os
import sys
import time
import enum
import json
import signal
import logging
import traceback
from pywren_ibm_cloud.invoker import Invoker
from pywren_ibm_cloud.storage import InternalStorage
from pywren_ibm_cloud.future import FunctionException
from pywren_ibm_cloud.monitor import wait_storage, wait_rabbitmq, ALL_COMPLETED
from pywren_ibm_cloud.storage.utils import clean_os_bucket
from pywren_ibm_cloud.job import create_call_async_job, create_map_job, create_reduce_job
from pywren_ibm_cloud.config import default_config, extract_storage_config, EXECUTION_TIMEOUT, default_logging_config
from pywren_ibm_cloud.utils import timeout_handler, is_notebook, is_unix_system, is_cf_cluster, create_executor_id

logger = logging.getLogger(__name__)


class ExecutorState(enum.Enum):
    new = 1
    running = 2
    ready = 3
    done = 4
    error = 5
    finished = 6


class JobState(enum.Enum):
    running = 1
    ready = 2
    done = 3
    finished = 4


class FunctionExecutor:

    def __init__(self, config=None, runtime=None, runtime_memory=None, compute_backend=None,
                 compute_backend_region=None, log_level=None, rabbitmq_monitor=None):
        """
        Initialize and return a ServerlessExecutor class.

        :param config: Settings passed in here will override those in config file. Default None.
        :param runtime: Runtime name to use. Default None.
        :param runtime_memory: memory to use in the runtime
        :param log_level: log level to use during the execution
        :param rabbitmq_monitor: use rabbitmq as monitoring system
        :return `ServerlessExecutor` object.
        """
        self.start_time = time.time()
        self._state = ExecutorState.new
        self.config = default_config(config)
        self.is_cf_cluster = is_cf_cluster()
        self.data_cleaner = self.config['pywren']['data_cleaner']

        # Overwrite runtime variables
        if runtime is not None:
            self.config['pywren']['runtime'] = runtime
        if runtime_memory is not None:
            self.config['pywren']['runtime_memory'] = int(runtime_memory)
        if compute_backend is not None:
            self.config['pywren']['compute_backend'] = compute_backend
        if compute_backend_region is not None:
            self.config['pywren']['compute_backend_region'] = compute_backend_region
        if rabbitmq_monitor is not None:
            self.config['pywren']['rabbitmq_monitor'] = rabbitmq_monitor

        # Log level Configuration
        self.log_level = log_level
        if not self.log_level:
            if(logger.getEffectiveLevel() != logging.WARNING):
                self.log_level = logging.getLevelName(logger.getEffectiveLevel())
        if self.log_level:
            os.environ["CB_LOG_LEVEL"] = self.log_level
            if not self.is_cf_cluster:
                default_logging_config(self.log_level)

        self.executor_id = create_executor_id()
        logger.debug('ServerlessExecutor created with ID: {}'.format(self.executor_id))

        # RabbitMQ monitor configuration
        self.rabbitmq_monitor = self.config['pywren'].get('rabbitmq_monitor', False)
        if self.rabbitmq_monitor:
            if 'rabbitmq' in self.config and 'amqp_url' in self.config['rabbitmq']:
                self.rabbit_amqp_url = self.config['rabbitmq'].get('amqp_url')
                os.environ["CB_RABBITMQ_MONITOR"] = 'True'
            else:
                raise Exception("RabbitMQ 'amqp_url' not provided in configuration")

        storage_config = extract_storage_config(self.config)
        self.internal_storage = InternalStorage(storage_config)
        self.invoker = Invoker(self.config, self.executor_id)
        self.jobs = {}

    @property
    def futures(self):
        futures = []
        for job in self.jobs:
            futures.extend(self.jobs[job]['futures'])
        return futures

    def call_async(self, func, data, extra_env=None, extra_meta=None, runtime_memory=None,
                   timeout=EXECUTION_TIMEOUT, exclude_modules=[]):
        """
        For running one function execution asynchronously
        :param func: the function to map over the data
        :param data: input data
        :param extra_env: Additional environment variables for action environment. Default None.
        :param extra_meta: Additional metadata to pass to action. Default None.
        """

        if self._state == ExecutorState.finished:
            raise Exception('You cannot run call_async() in the current state,'
                            ' create a new FunctionExecutor() instance.')
        total_current_jobs = len(self.jobs)
        job = create_call_async_job(self.config, self.internal_storage, self.executor_id,
                                    total_current_jobs, func, data, extra_env, extra_meta,
                                    runtime_memory, timeout, exclude_modules=exclude_modules)
        future = self.invoker.run(job)
        self.jobs[job['job_id']] = {'futures': future, 'state': JobState.running}
        self._state = ExecutorState.running

        return future[0]

    def map(self, map_function, map_iterdata, extra_env=None, extra_meta=None, runtime_memory=None,
            chunk_size=None, chunk_n=None, remote_invocation=False, remote_invocation_groups=None,
            timeout=EXECUTION_TIMEOUT, invoke_pool_threads=500, overwrite_invoke_args=None, exclude_modules=[]):
        """
        :param func: the function to map over the data
        :param iterdata: An iterable of input data
        :param extra_env: Additional environment variables for action environment. Default None.
        :param extra_meta: Additional metadata to pass to action. Default None.
        :param chunk_size: the size of the data chunks. 'None' for processing the whole file in one map
        :param remote_invocation: Enable or disable remote_invocayion mechanism. Default 'False'
        :param timeout: Time that the functions have to complete their execution before raising a timeout.
        :param data_type: the type of the data. Now allowed: None (files with newline) and csv.
        :param invoke_pool_threads: Number of threads to use to invoke.
        :param data_all_as_one: upload the data as a single object. Default True
        :param overwrite_invoke_args: Overwrite other args. Mainly used for testing.
        :param exclude_modules: Explicitly keep these modules from pickled dependencies.
        :return: A list with size `len(iterdata)` of futures for each job
        :rtype: list of futures.
        """
        if self._state == ExecutorState.finished:
            raise Exception('You cannot run map() in the current state.'
                            ' Create a new FunctionExecutor() instance.')
        total_current_jobs = len(self.jobs)
        job, unused_ppo = create_map_job(self.config, self.internal_storage,
                                         self.executor_id, total_current_jobs,
                                         map_function=map_function, iterdata=map_iterdata,
                                         extra_env=extra_env, extra_meta=extra_meta,
                                         obj_chunk_size=chunk_size, obj_chunk_number=chunk_n,
                                         runtime_memory=runtime_memory,
                                         remote_invocation=remote_invocation,
                                         remote_invocation_groups=remote_invocation_groups,
                                         invoke_pool_threads=invoke_pool_threads,
                                         exclude_modules=exclude_modules,
                                         is_cf_cluster=self.is_cf_cluster,
                                         overwrite_invoke_args=overwrite_invoke_args,
                                         execution_timeout=timeout)
        map_futures = self.invoker.run(job)
        self.jobs[job['job_id']] = {'futures': map_futures, 'state': JobState.running}
        self._state = ExecutorState.running

        if len(map_futures) == 1:
            return map_futures[0]
        return map_futures

    def map_reduce(self, map_function, map_iterdata, reduce_function, extra_env=None, map_runtime_memory=None,
                   reduce_runtime_memory=None, extra_meta=None, chunk_size=None,  chunk_n=None, remote_invocation=False,
                   remote_invocation_groups=None, timeout=EXECUTION_TIMEOUT, reducer_one_per_object=False,
                   reducer_wait_local=False, invoke_pool_threads=500, overwrite_invoke_args=None, exclude_modules=[]):
        """
        Map the map_function over the data and apply the reduce_function across all futures.
        This method is executed all within CF.
        :param map_function: the function to map over the data
        :param map_iterdata:  the function to reduce over the futures
        :param reduce_function:  the function to reduce over the futures
        :param extra_env: Additional environment variables for action environment. Default None.
        :param extra_meta: Additional metadata to pass to action. Default None.
        :param chunk_size: the size of the data chunks. 'None' for processing the whole file in one map
        :param remote_invocation: Enable or disable remote_invocayion mechanism. Default 'False'
        :param timeout: Time that the functions have to complete their execution before raising a timeout.
        :param data_type: the type of the data. Now allowed: None (files with newline) and csv.
        :param reducer_one_per_object: Set one reducer per object after running the partitioner
        :param reducer_wait_local: Wait for results locally
        :param invoke_pool_threads: Number of threads to use to invoke.
        :param data_all_as_one: upload the data as a single object. Default True
        :param overwrite_invoke_args: Overwrite other args. Mainly used for testing.
        :param exclude_modules: Explicitly keep these modules from pickled dependencies.
        :return: A list with size `len(map_iterdata)` of futures for each job
        """

        if self._state == ExecutorState.finished:
            raise Exception('You cannot run map_reduce() in the current state.'
                            ' Create a new FunctionExecutor() instance.')
        total_current_jobs = len(self.jobs)
        job, parts_per_object = create_map_job(self.config, self.internal_storage,
                                               self.executor_id, total_current_jobs,
                                               map_function=map_function, iterdata=map_iterdata,
                                               extra_env=extra_env, extra_meta=extra_meta,
                                               obj_chunk_size=chunk_size, obj_chunk_number=chunk_n,
                                               runtime_memory=map_runtime_memory,
                                               remote_invocation=remote_invocation,
                                               remote_invocation_groups=remote_invocation_groups,
                                               invoke_pool_threads=invoke_pool_threads,
                                               exclude_modules=exclude_modules,
                                               is_cf_cluster=self.is_cf_cluster,
                                               overwrite_invoke_args=overwrite_invoke_args,
                                               execution_timeout=timeout)
        map_futures = self.invoker.run(job)
        self.jobs[job['job_id']] = {'futures': map_futures, 'state': JobState.running}
        self._state = ExecutorState.running

        if reducer_wait_local:
            self.monitor(futures=map_futures)

        job = create_reduce_job(self.config, self.internal_storage, self.executor_id,
                                total_current_jobs, reduce_function, reduce_runtime_memory,
                                map_futures, parts_per_object, reducer_one_per_object=reducer_one_per_object,
                                extra_env=extra_env, extra_meta=extra_meta, exclude_modules=exclude_modules)
        reduce_futures = self.invoker.run(job)
        self.jobs[job['job_id']] = {'futures': reduce_futures, 'state': JobState.running}

        for f in map_futures:
            f.produce_output = False

        return map_futures + reduce_futures

    def monitor(self, futures=None, throw_except=True, return_when=ALL_COMPLETED,
                download_results=False, timeout=EXECUTION_TIMEOUT,
                THREADPOOL_SIZE=128, WAIT_DUR_SEC=1):
        """
        Wait for the Future instances `fs` to complete. Returns a 2-tuple of
        lists. The first list contains the futures that completed
        (finished or cancelled) before the wait completed. The second
        contains uncompleted futures.
        :param futures: Futures list. Default None
        :param throw_except: Re-raise exception if call raised. Default True.
        :param return_when: One of `ALL_COMPLETED`, `ANY_COMPLETED`, `ALWAYS`
        :param download_results: Download results. Default false (Only get statuses)
        :param timeout: Timeout of waiting for results.
        :param THREADPOOL_SIZE: Number of threads to use. Default 64
        :param WAIT_DUR_SEC: Time interval between each check.
        :return: `(fs_done, fs_notdone)`
            where `fs_done` is a list of futures that have completed
            and `fs_notdone` is a list of futures that have not completed.
        :rtype: 2-tuple of list
        """
        if not futures:
            futures = []
            for job in self.jobs:
                if not download_results and self.jobs[job]['state'] == JobState.running:
                    futures.extend(self.jobs[job]['futures'])
                    self.jobs[job]['state'] = JobState.ready
                elif download_results and self.jobs[job]['state'] != JobState.done:
                    futures.extend(self.jobs[job]['futures'])
                    self.jobs[job]['state'] = JobState.done

        if type(futures) != list:
            ftrs = [futures]
        else:
            ftrs = futures

        if not ftrs:
            raise Exception('You must run the call_async(), map() or map_reduce(), or provide'
                            ' a list of futures before calling the monitor()/get_result() method')

        if download_results:
            msg = 'ExecutorID {} - Getting results...'.format(self.executor_id)
        else:
            msg = 'ExecutorID {} - Waiting for functions to complete...'.format(self.executor_id)
        logger.info(msg)
        if not self.log_level and self._state == ExecutorState.running:
            print(msg)

        if is_unix_system():
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout)

        pbar = None
        if not self.is_cf_cluster and self._state == ExecutorState.running \
           and not self.log_level:
            from tqdm.auto import tqdm
            if is_notebook():
                pbar = tqdm(bar_format='{n}/|/ {n_fmt}/{total_fmt}', total=len(ftrs))  # ncols=800
            else:
                print()
                pbar = tqdm(bar_format='  {l_bar}{bar}| {n_fmt}/{total_fmt}  ', total=len(ftrs), disable=False)

        try:
            if self.rabbitmq_monitor:
                logger.info('Using RabbitMQ to monitor function activations')
                wait_rabbitmq(ftrs, self.internal_storage, rabbit_amqp_url=self.rabbit_amqp_url,
                              download_results=download_results, throw_except=throw_except,
                              pbar=pbar, return_when=return_when, THREADPOOL_SIZE=THREADPOOL_SIZE)
            else:
                wait_storage(ftrs, self.internal_storage, download_results=download_results,
                             throw_except=throw_except, return_when=return_when, pbar=pbar,
                             THREADPOOL_SIZE=THREADPOOL_SIZE, WAIT_DUR_SEC=WAIT_DUR_SEC)

        except FunctionException as e:
            if is_unix_system():
                signal.alarm(0)
            if pbar:
                pbar.close()
            logger.info(e.msg)
            if not is_notebook():
                print()
            if not self.log_level:
                print(e.msg)
            if e.exc_msg:
                print('--> Exception: ' + e.exc_msg)
            else:
                print()
                traceback.print_exception(*e.exception)
            sys.exit()

        except TimeoutError:
            if download_results:
                not_dones_activation_ids = [f.activation_id for f in ftrs if not f.done]
            else:
                not_dones_activation_ids = [f.activation_id for f in ftrs if not f.ready and not f.done]
            msg = ('ExecutorID {} - Raised timeout of {} seconds waiting for results - Total Activations not done: {}'
                   ' {}'.format(self.executor_id, timeout, len(not_dones_activation_ids), not_dones_activation_ids))
            self._state = ExecutorState.error

        except KeyboardInterrupt:
            if download_results:
                not_dones_activation_ids = [f.activation_id for f in ftrs if not f.done]
            else:
                not_dones_activation_ids = [f.activation_id for f in ftrs if not f.ready and not f.done]
            msg = ('ExecutorID {} - Cancelled - Total Activations not done: {} '
                   '{}'.format(self.executor_id, len(not_dones_activation_ids), not_dones_activation_ids))
            self._state = ExecutorState.error

        except Exception as e:
            if not self.is_cf_cluster:
                self.clean()
            raise e

        finally:
            if is_unix_system():
                signal.alarm(0)
            if pbar:
                pbar.close()
                if not is_notebook():
                    print()
            if self._state == ExecutorState.error:
                logger.debug(msg)
                if not self.log_level:
                    print(msg)
            if download_results and self.data_cleaner and not self.is_cf_cluster:
                self.clean()

        if download_results:
            fs_dones = [f for f in ftrs if f.done]
            fs_notdones = [f for f in ftrs if not f.done]
            self._state = ExecutorState.ready
        else:
            fs_dones = [f for f in ftrs if f.ready or f.done]
            fs_notdones = [f for f in ftrs if not f.ready and not f.done]
            self._state = ExecutorState.done

        return fs_dones, fs_notdones

    def get_result(self, futures=None, throw_except=True, timeout=EXECUTION_TIMEOUT,
                   THREADPOOL_SIZE=128, WAIT_DUR_SEC=1):
        """
        For getting results
        :param futures: Futures list. Default None
        :param throw_except: Reraise exception if call raised. Default True.
        :param verbose: Shows some information prints. Default False
        :param timeout: Timeout for waiting for results.
        :param THREADPOOL_SIZE: Number of threads to use. Default 64
        :param WAIT_DUR_SEC: Time interval between each check.
        :return: The result of the future/s
        """
        fs_dones, unused_fs_notdones = self.monitor(futures=futures,
                                                    throw_except=throw_except,
                                                    timeout=timeout,
                                                    download_results=True,
                                                    THREADPOOL_SIZE=THREADPOOL_SIZE,
                                                    WAIT_DUR_SEC=WAIT_DUR_SEC)
        result = [f.result(internal_storage=self.internal_storage)
                  for f in fs_dones if not f.futures and f.produce_output]
        msg = "ExecutorID {} Finished getting results".format(self.executor_id)
        logger.debug(msg)
        if result and len(result) == 1:
            return result[0]
        return result

    def create_timeline_plots(self, dst_dir, dst_file_name, futures=None):
        """
        Creates timeline and histogram of the current execution in dst_dir.

        :param futures: list of futures.
        :param dst_dir: destination folder to save .png plots.
        :param dst_file_name: name of the file.
        """
        if not futures:
            futures = []
            for job in self.jobs:
                if self.jobs[job]['state'] == JobState.ready or \
                   self.jobs[job]['state'] == JobState.done:
                    futures.extend(self.jobs[job]['futures'])
                    self.jobs[job]['state'] = JobState.finished

        if type(futures) != list:
            ftrs = [futures]
        else:
            ftrs = futures

        ftrs_to_plot = [f for f in ftrs if f.ready or f.done]

        if not ftrs_to_plot:
            msg = ('You must run call_async(), map() or map_reduce()'
                   ' followed by monitor() or get_results()'
                   ' before calling create_timeline_plots() method')
            logger.debug(msg)
            return

        logging.getLogger('matplotlib').setLevel(logging.WARNING)
        from pywren_ibm_cloud.plots import create_timeline, create_histogram

        msg = 'ExecutorID {} - Creating timeline plots'.format(self.executor_id)
        logger.info(msg)
        if not self.log_level:
            print(msg)

        run_statuses = [f.run_status for f in ftrs_to_plot]
        invoke_statuses = [f.invoke_status for f in ftrs_to_plot]

        create_timeline(dst_dir, dst_file_name, self.start_time, run_statuses, invoke_statuses, self.config['ibm_cos'])
        create_histogram(dst_dir, dst_file_name, self.start_time, run_statuses, self.config['ibm_cos'])

    def clean(self, local_execution=True, delete_all=False):
        """
        Deletes all the files from COS. These files include the function,
        the data serialization and the function invocation results.
        """
        storage_bucket = self.config['pywren']['storage_bucket']
        storage_prerix = self.config['pywren']['storage_prefix']
        if delete_all:
            storage_prerix = '/'.join([storage_prerix])
        else:
            storage_prerix = '/'.join([storage_prerix, self.executor_id])
        msg = "ExecutorID {} - Cleaning temporary data".format(self.executor_id)
        logger.info(msg)
        if not self.log_level:
            print(msg)

        if local_execution:
            # 1st case: Not background. The main code waits until the cleaner finishes its execution.
            # It is not ideal for performance tests, since it can take long time to complete.
            # clean_os_bucket(storage_bucket, storage_prerix, self.internal_storage)

            # 2nd case: Execute in Background as a subprocess. The main program does not wait for its completion.
            storage_config = json.dumps(self.internal_storage.get_storage_config())
            storage_config = storage_config.replace('"', '\\"')

            cmdstr = ("{} -c 'from pywren_ibm_cloud.storage.utils import clean_bucket; \
                              clean_bucket(\"{}\", \"{}\", \"{}\")'".format(sys.executable,
                                                                            storage_bucket,
                                                                            storage_prerix,
                                                                            storage_config))
            os.popen(cmdstr)

        else:
            extra_env = {'STORE_STATUS': False,
                         'STORE_RESULT': False}
            old_stdout = sys.stdout
            sys.stdout = open(os.devnull, 'w')
            self.executor.call_async(clean_os_bucket, [storage_bucket, storage_prerix], extra_env=extra_env)
            sys.stdout = old_stdout

        self._state = ExecutorState.finished
