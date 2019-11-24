import os
import sys
import time
import json
import signal
import logging
import traceback
from pywren_ibm_cloud.invoker import FunctionInvoker
from pywren_ibm_cloud.storage import InternalStorage
from pywren_ibm_cloud.future import FunctionException
from pywren_ibm_cloud.storage.utils import clean_os_bucket
from pywren_ibm_cloud.wait import wait_storage, wait_rabbitmq, ALL_COMPLETED
from pywren_ibm_cloud.job import JobState, create_map_job, create_reduce_job
from pywren_ibm_cloud.config import default_config, extract_storage_config, EXECUTION_TIMEOUT, default_logging_config
from pywren_ibm_cloud.utils import timeout_handler, is_notebook, is_unix_system, is_remote_cluster, create_executor_id

logger = logging.getLogger(__name__)


class FunctionExecutor:

    class State:
        New = 'New'
        Running = 'Running'
        Ready = 'Ready'
        Done = 'Done'
        Error = 'Error'
        Finished = 'Finished'

    def __init__(self, config=None, runtime=None, runtime_memory=None, compute_backend=None,
                 compute_backend_region=None, storage_backend=None, storage_backend_region=None,
                 rabbitmq_monitor=None, log_level=None):
        """
        Initialize a FunctionExecutor class.

        :param config: Settings passed in here will override those in config file. Default None.
        :param runtime: Runtime name to use. Default None.
        :param runtime_memory: memory to use in the runtime. Default None.
        :param compute_backend: Name of the compute backend to use. Default None.
        :param compute_backend_region: Name of the compute backend region to use. Default None.
        :param storage_backend: Name of the storage backend to use. Default None.
        :param storage_backend_region: Name of the storage backend region to use. Default None.
        :param log_level: log level to use during the execution. Default None.
        :param rabbitmq_monitor: use rabbitmq as the monitoring system. Default None.

        :return `FunctionExecutor` object.
        """
        self.start_time = time.time()
        self._state = FunctionExecutor.State.New
        self.is_remote_cluster = is_remote_cluster()

        # Log level Configuration
        self.log_level = log_level
        if not self.log_level:
            if(logger.getEffectiveLevel() != logging.WARNING):
                self.log_level = logging.getLevelName(logger.getEffectiveLevel())
        if self.log_level:
            os.environ["PYWREN_LOGLEVEL"] = self.log_level
            if not self.is_remote_cluster:
                default_logging_config(self.log_level)

        # Overwrite pywren config parameters
        config_ow = {'pywren': {}}
        if runtime is not None:
            config_ow['pywren']['runtime'] = runtime
        if runtime_memory is not None:
            config_ow['pywren']['runtime_memory'] = int(runtime_memory)
        if compute_backend is not None:
            config_ow['pywren']['compute_backend'] = compute_backend
        if compute_backend_region is not None:
            config_ow['pywren']['compute_backend_region'] = compute_backend_region
        if storage_backend is not None:
            config_ow['pywren']['storage_backend'] = storage_backend
        if storage_backend_region is not None:
            config_ow['pywren']['storage_backend_region'] = storage_backend_region
        if rabbitmq_monitor is not None:
            config_ow['pywren']['rabbitmq_monitor'] = rabbitmq_monitor

        self.config = default_config(config, config_ow)

        self.executor_id = create_executor_id()
        logger.debug('FunctionExecutor created with ID: {}'.format(self.executor_id))

        # RabbitMQ monitor configuration
        self.rabbitmq_monitor = self.config['pywren'].get('rabbitmq_monitor', False)
        if self.rabbitmq_monitor:
            if 'rabbitmq' in self.config and 'amqp_url' in self.config['rabbitmq']:
                self.rabbit_amqp_url = self.config['rabbitmq'].get('amqp_url')
            else:
                raise Exception("You cannot use rabbitmq_mnonitor since 'amqp_url'"
                                " is not present in configuration")
        self.data_cleaner = self.config['pywren']['data_cleaner']

        storage_config = extract_storage_config(self.config)
        self.internal_storage = InternalStorage(storage_config)
        self.invoker = FunctionInvoker(self.config, self.executor_id, self.internal_storage)

        self.jobs = {}

    @property
    def futures(self):
        futures = []
        for job in self.jobs:
            futures.extend(self.jobs[job]['futures'])
        return futures

    def call_async(self, func, data, extra_env=None, runtime_memory=None,
                   timeout=EXECUTION_TIMEOUT, include_modules=[], exclude_modules=[]):
        """
        For running one function execution asynchronously

        :param func: the function to map over the data
        :param data: input data
        :param extra_data: Additional data to pass to action. Default None.
        :param extra_env: Additional environment variables for action environment. Default None.
        :param runtime_memory: Memory to use to run the function. Default None (loaded from config).
        :param timeout: Time that the functions have to complete their execution before raising a timeout.
        :param include_modules: Explicitly pickle these dependencies.
        :param exclude_modules: Explicitly keep these modules from pickled dependencies.

        :return: future object.
        """
        if self._state == FunctionExecutor.State.Finished:
            raise Exception('You cannot run call_async() in the current state,'
                            ' create a new FunctionExecutor() instance.')

        job_id = str(len(self.jobs)).zfill(3)
        async_job_id = 'A{}'.format(job_id)

        runtime_meta = self.invoker.select_runtime(async_job_id, runtime_memory)

        job = create_map_job(self.config, self.internal_storage,
                             self.executor_id, async_job_id,
                             map_function=func,
                             iterdata=[data],
                             runtime_meta=runtime_meta,
                             runtime_memory=runtime_memory,
                             extra_env=extra_env,
                             include_modules=include_modules,
                             exclude_modules=exclude_modules,
                             execution_timeout=timeout)

        future = self.invoker.run(job)
        self.jobs[async_job_id] = {'futures': future, 'state': JobState.Running}
        self._state = FunctionExecutor.State.Running

        return future[0]

    def map(self, map_function, map_iterdata, extra_params=None, extra_env=None, runtime_memory=None,
            chunk_size=None, chunk_n=None, remote_invocation=False, remote_invocation_groups=None,
            timeout=EXECUTION_TIMEOUT, invoke_pool_threads=500, include_modules=[], exclude_modules=[]):
        """
        :param map_function: the function to map over the data
        :param map_iterdata: An iterable of input data
        :param extra_params: Additional parameters to pass to the function activation. Default None.
        :param extra_env: Additional environment variables for action environment. Default None.
        :param runtime_memory: Memory to use to run the function. Default None (loaded from config).
        :param chunk_size: the size of the data chunks to split each object. 'None' for processing
                           the whole file in one function activation.
        :param chunk_n: Number of chunks to split each object. 'None' for processing the whole
                        file in one function activation.
        :param remote_invocation: Enable or disable remote_invocation mechanism. Default 'False'
        :param timeout: Time that the functions have to complete their execution before raising a timeout.
        :param invoke_pool_threads: Number of threads to use to invoke.
        :param include_modules: Explicitly pickle these dependencies.
        :param exclude_modules: Explicitly keep these modules from pickled dependencies.

        :return: A list with size `len(iterdata)` of futures.
        """
        if self._state == FunctionExecutor.State.Finished:
            raise Exception('You cannot run map() in the current state.'
                            ' Create a new FunctionExecutor() instance.')

        total_current_jobs = len(self.jobs)
        job_id = str(total_current_jobs).zfill(3)
        map_job_id = 'M{}'.format(job_id)

        runtime_meta = self.invoker.select_runtime(map_job_id, runtime_memory)

        job = create_map_job(self.config, self.internal_storage,
                             self.executor_id, map_job_id,
                             map_function=map_function,
                             iterdata=map_iterdata,
                             runtime_meta=runtime_meta,
                             runtime_memory=runtime_memory,
                             extra_params=extra_params,
                             extra_env=extra_env,
                             obj_chunk_size=chunk_size,
                             obj_chunk_number=chunk_n,
                             remote_invocation=remote_invocation,
                             remote_invocation_groups=remote_invocation_groups,
                             invoke_pool_threads=invoke_pool_threads,
                             include_modules=include_modules,
                             exclude_modules=exclude_modules,
                             is_remote_cluster=self.is_remote_cluster,
                             execution_timeout=timeout)

        map_futures = self.invoker.run(job)
        self.jobs[map_job_id] = {'futures': map_futures, 'state': JobState.Running}
        self._state = FunctionExecutor.State.Running
        if len(map_futures) == 1:
            return map_futures[0]
        return map_futures

    def map_reduce(self, map_function, map_iterdata, reduce_function, extra_params=None, extra_env=None,
                   map_runtime_memory=None, reduce_runtime_memory=None, chunk_size=None, chunk_n=None,
                   remote_invocation=False, remote_invocation_groups=None, timeout=EXECUTION_TIMEOUT,
                   reducer_one_per_object=False, reducer_wait_local=False, invoke_pool_threads=500,
                   include_modules=[], exclude_modules=[]):
        """
        Map the map_function over the data and apply the reduce_function across all futures.
        This method is executed all within CF.

        :param map_function: the function to map over the data
        :param map_iterdata:  the function to reduce over the futures
        :param reduce_function:  the function to reduce over the futures
        :param extra_env: Additional environment variables for action environment. Default None.
        :param extra_params: Additional parameters to pass to function activation. Default None.
        :param map_runtime_memory: Memory to use to run the map function. Default None (loaded from config).
        :param reduce_runtime_memory: Memory to use to run the reduce function. Default None (loaded from config).
        :param chunk_size: the size of the data chunks to split each object. 'None' for processing
                           the whole file in one function activation.
        :param chunk_n: Number of chunks to split each object. 'None' for processing the whole
                        file in one function activation.
        :param remote_invocation: Enable or disable remote_invocation mechanism. Default 'False'
        :param timeout: Time that the functions have to complete their execution before raising a timeout.
        :param reducer_one_per_object: Set one reducer per object after running the partitioner
        :param reducer_wait_local: Wait for results locally
        :param invoke_pool_threads: Number of threads to use to invoke.
        :param include_modules: Explicitly pickle these dependencies.
        :param exclude_modules: Explicitly keep these modules from pickled dependencies.

        :return: A list with size `len(map_iterdata)` of futures.
        """
        if self._state == FunctionExecutor.State.Finished:
            raise Exception('You cannot run map_reduce() in the current state.'
                            ' Create a new FunctionExecutor() instance.')

        total_current_jobs = len(self.jobs)
        job_id = str(total_current_jobs).zfill(3)
        map_job_id = 'M{}'.format(job_id)

        runtime_meta = self.invoker.select_runtime(map_job_id, map_runtime_memory)

        map_job = create_map_job(self.config, self.internal_storage,
                                 self.executor_id, map_job_id,
                                 map_function=map_function,
                                 iterdata=map_iterdata,
                                 runtime_meta=runtime_meta,
                                 runtime_memory=map_runtime_memory,
                                 extra_params=extra_params,
                                 extra_env=extra_env,
                                 obj_chunk_size=chunk_size,
                                 obj_chunk_number=chunk_n,
                                 remote_invocation=remote_invocation,
                                 remote_invocation_groups=remote_invocation_groups,
                                 invoke_pool_threads=invoke_pool_threads,
                                 include_modules=include_modules,
                                 exclude_modules=exclude_modules,
                                 is_remote_cluster=self.is_remote_cluster,
                                 execution_timeout=timeout)

        map_futures = self.invoker.run(map_job)
        self.jobs[map_job_id] = {'futures': map_futures, 'state': JobState.Running}
        self._state = FunctionExecutor.State.Running

        if reducer_wait_local:
            self.wait(fs=map_futures)

        reduce_job_id = 'R{}'.format(job_id)

        runtime_meta = self.invoker.select_runtime(reduce_job_id, reduce_runtime_memory)

        reduce_job = create_reduce_job(self.config, self.internal_storage,
                                       self.executor_id, reduce_job_id,
                                       reduce_function, map_job, map_futures,
                                       runtime_meta=runtime_meta,
                                       reducer_one_per_object=reducer_one_per_object,
                                       runtime_memory=reduce_runtime_memory,
                                       extra_env=extra_env,
                                       include_modules=include_modules,
                                       exclude_modules=exclude_modules)

        reduce_futures = self.invoker.run(reduce_job)
        self.jobs[reduce_job_id] = {'futures': reduce_futures, 'state': JobState.Running}

        for f in map_futures:
            f.produce_output = False

        return map_futures + reduce_futures

    def wait(self, fs=None, throw_except=True, return_when=ALL_COMPLETED, download_results=False,
             timeout=EXECUTION_TIMEOUT, THREADPOOL_SIZE=128, WAIT_DUR_SEC=1):
        """
        Wait for the Future instances (possibly created by different Executor instances)
        given by fs to complete. Returns a named 2-tuple of sets. The first set, named done,
        contains the futures that completed (finished or cancelled futures) before the wait
        completed. The second set, named not_done, contains the futures that did not complete
        (pending or running futures). timeout can be used to control the maximum number of
        seconds to wait before returning.

        :param fs: Futures list. Default None
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
        if not fs:
            fs = []
            for job in self.jobs:
                if not download_results and self.jobs[job]['state'] == JobState.Running:
                    fs.extend(self.jobs[job]['futures'])
                    self.jobs[job]['state'] = JobState.Ready
                elif download_results and self.jobs[job]['state'] != JobState.Done:
                    fs.extend(self.jobs[job]['futures'])
                    self.jobs[job]['state'] = JobState.Done

        if type(fs) != list:
            futures = [fs]
        else:
            futures = fs

        if not futures:
            raise Exception('You must run the call_async(), map() or map_reduce(), or provide'
                            ' a list of futures before calling the monitor()/get_result() method')

        if download_results:
            msg = 'ExecutorID {} - Getting results...'.format(self.executor_id)
        else:
            msg = 'ExecutorID {} - Waiting for functions to complete...'.format(self.executor_id)
        logger.info(msg)
        if not self.log_level and self._state == FunctionExecutor.State.Running:
            print(msg)

        if is_unix_system():
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout)

        pbar = None
        if not self.is_remote_cluster and self._state == FunctionExecutor.State.Running \
           and not self.log_level:
            from tqdm.auto import tqdm
            if is_notebook():
                pbar = tqdm(bar_format='{n}/|/ {n_fmt}/{total_fmt}', total=len(futures))  # ncols=800
            else:
                print()
                pbar = tqdm(bar_format='  {l_bar}{bar}| {n_fmt}/{total_fmt}  ', total=len(futures), disable=False)

        try:
            if self.rabbitmq_monitor:
                logger.info('Using RabbitMQ to monitor function activations')
                wait_rabbitmq(futures, self.internal_storage, rabbit_amqp_url=self.rabbit_amqp_url,
                              download_results=download_results, throw_except=throw_except,
                              pbar=pbar, return_when=return_when, THREADPOOL_SIZE=THREADPOOL_SIZE)
            else:
                wait_storage(futures, self.internal_storage, download_results=download_results,
                             throw_except=throw_except, return_when=return_when, pbar=pbar,
                             THREADPOOL_SIZE=THREADPOOL_SIZE, WAIT_DUR_SEC=WAIT_DUR_SEC)

        except FunctionException as e:
            if is_unix_system():
                signal.alarm(0)
            if pbar:
                pbar.close()
            logger.info(e.msg)
            if not self.log_level:
                if not is_notebook():
                    print()
                print(e.msg)
            if e.exc_msg:
                logger.info('Exception: ' + e.exc_msg)
                if not self.log_level:
                    print('--> Exception: ' + e.exc_msg)
            else:
                print()
                traceback.print_exception(*e.exception)
            sys.exit()

        except TimeoutError:
            if download_results:
                not_dones_call_ids = [(f.job_id, f.call_id) for f in futures if not f.done]
            else:
                not_dones_call_ids = [(f.job_id, f.call_id) for f in futures if not f.ready and not f.done]
            msg = ('ExecutorID {} - Raised timeout of {} seconds waiting for results - Total Activations not done: {}'
                   .format(self.executor_id, timeout, len(not_dones_call_ids)))
            self._state = FunctionExecutor.State.Error

        except KeyboardInterrupt:
            if download_results:
                not_dones_call_ids = [(f.job_id, f.call_id) for f in futures if not f.done]
            else:
                not_dones_call_ids = [(f.job_id, f.call_id) for f in futures if not f.ready and not f.done]
            msg = ('ExecutorID {} - Cancelled - Total Activations not done: {}'
                   .format(self.executor_id, len(not_dones_call_ids)))
            self._state = FunctionExecutor.State.Error

        except Exception as e:
            if not self.is_remote_cluster:
                self.clean()
            raise e

        finally:
            if is_unix_system():
                signal.alarm(0)
            if pbar:
                pbar.close()
                if not is_notebook():
                    print()
            if self._state == FunctionExecutor.State.Error:
                logger.debug(msg)
                if not self.log_level:
                    print(msg)
            if download_results and self.data_cleaner and not self.is_remote_cluster:
                self.clean()

        if download_results:
            fs_done = [f for f in futures if f.done]
            fs_notdone = [f for f in futures if not f.done]
            self._state = FunctionExecutor.State.Done
        else:
            fs_done = [f for f in futures if f.ready or f.done]
            fs_notdone = [f for f in futures if not f.ready and not f.done]
            self._state = FunctionExecutor.State.Ready

        return fs_done, fs_notdone

    def get_result(self, fs=None, throw_except=True, timeout=EXECUTION_TIMEOUT,
                   THREADPOOL_SIZE=128, WAIT_DUR_SEC=1):
        """
        For getting the results from all function activations

        :param fs: Futures list. Default None
        :param throw_except: Reraise exception if call raised. Default True.
        :param verbose: Shows some information prints. Default False
        :param timeout: Timeout for waiting for results.
        :param THREADPOOL_SIZE: Number of threads to use. Default 128
        :param WAIT_DUR_SEC: Time interval between each check.

        :return: The result of the future/s
        """
        fs_done, unused_fs_notdone = self.wait(fs=fs, throw_except=throw_except,
                                               timeout=timeout, download_results=True,
                                               THREADPOOL_SIZE=THREADPOOL_SIZE,
                                               WAIT_DUR_SEC=WAIT_DUR_SEC)
        result = [f.result(throw_except=throw_except, internal_storage=self.internal_storage)
                  for f in fs_done if not f.futures and f.produce_output]
        msg = "ExecutorID {} Finished getting results".format(self.executor_id)
        logger.debug(msg)
        if result and len(result) == 1:
            return result[0]
        return result

    def create_execution_plots(self, dst_dir, dst_file_name, futures=None):
        """
        Creates timeline and histogram of the current execution in dst_dir.

        :param futures: list of futures.
        :param dst_dir: destination folder to save .png plots.
        :param dst_file_name: name of the file.
        """
        if not futures:
            futures = []
            for job in self.jobs:
                if self.jobs[job]['state'] == JobState.Ready or \
                   self.jobs[job]['state'] == JobState.Done:
                    futures.extend(self.jobs[job]['futures'])
                    self.jobs[job]['state'] = JobState.Finished

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

        msg = 'ExecutorID {} - Creating execution plots'.format(self.executor_id)
        logger.info(msg)
        if not self.log_level:
            print(msg)

        call_status = [f._call_status for f in ftrs_to_plot]
        call_metadata = [f._call_metadata for f in ftrs_to_plot]

        create_timeline(dst_dir, dst_file_name, self.start_time, call_status, call_metadata, self.config['ibm_cos'])
        create_histogram(dst_dir, dst_file_name, self.start_time, call_status, self.config['ibm_cos'])

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
            self.call_async(clean_os_bucket, [storage_bucket, storage_prerix], extra_env=extra_env)
            sys.stdout = old_stdout

        self._state = FunctionExecutor.State.Finished
