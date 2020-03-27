import os
import sys
import copy
import time
import json
import signal
import logging
from functools import partial
from pywren_ibm_cloud.invoker import FunctionInvoker
from pywren_ibm_cloud.storage import InternalStorage
from pywren_ibm_cloud.storage.utils import clean_os_bucket
from pywren_ibm_cloud.wait import wait_storage, wait_rabbitmq, ALL_COMPLETED
from pywren_ibm_cloud.job import create_map_job, create_reduce_job
from pywren_ibm_cloud.config import default_config, extract_storage_config, JOBS_PREFIX, default_logging_config
from pywren_ibm_cloud.utils import timeout_handler, is_notebook, is_unix_system, is_pywren_function, create_executor_id

logger = logging.getLogger(__name__)


class FunctionExecutor:

    class State:
        New = 'New'
        Running = 'Running'
        Ready = 'Ready'
        Done = 'Done'
        Error = 'Error'

    def __init__(self, config=None, runtime=None, runtime_memory=None, compute_backend=None,
                 compute_backend_region=None, storage_backend=None, storage_backend_region=None,
                 workers=None, rabbitmq_monitor=None, remote_invoker=None, log_level=None):
        """
        Initialize a FunctionExecutor class.

        :param config: Settings passed in here will override those in config file. Default None.
        :param runtime: Runtime name to use. Default None.
        :param runtime_memory: memory to use in the runtime. Default None.
        :param compute_backend: Name of the compute backend to use. Default None.
        :param compute_backend_region: Name of the compute backend region to use. Default None.
        :param storage_backend: Name of the storage backend to use. Default None.
        :param storage_backend_region: Name of the storage backend region to use. Default None.
        :param workers: Max number of concurrent workers.
        :param rabbitmq_monitor: use rabbitmq as the monitoring system. Default None.
        :param log_level: log level to use during the execution. Default None.

        :return `FunctionExecutor` object.
        """
        self.start_time = time.time()
        self._state = FunctionExecutor.State.New
        self.is_pywren_function = is_pywren_function()

        # Log level Configuration
        self.log_level = log_level
        if not self.log_level:
            if(logger.getEffectiveLevel() != logging.WARNING):
                self.log_level = logging.getLevelName(logger.getEffectiveLevel())
        if self.log_level:
            os.environ["PYWREN_LOGLEVEL"] = self.log_level
            if not self.is_pywren_function:
                default_logging_config(self.log_level)

        # Overwrite pywren config parameters
        pw_config_ow = {}
        if runtime is not None:
            pw_config_ow['runtime'] = runtime
        if runtime_memory is not None:
            pw_config_ow['runtime_memory'] = int(runtime_memory)
        if compute_backend is not None:
            pw_config_ow['compute_backend'] = compute_backend
        if compute_backend_region is not None:
            pw_config_ow['compute_backend_region'] = compute_backend_region
        if storage_backend is not None:
            pw_config_ow['storage_backend'] = storage_backend
        if storage_backend_region is not None:
            pw_config_ow['storage_backend_region'] = storage_backend_region
        if workers is not None:
            pw_config_ow['workers'] = workers
        if rabbitmq_monitor is not None:
            pw_config_ow['rabbitmq_monitor'] = rabbitmq_monitor
        if remote_invoker is not None:
            pw_config_ow['remote_invoker'] = remote_invoker

        self.config = default_config(copy.deepcopy(config), pw_config_ow)

        self.executor_id = create_executor_id()
        logger.debug('FunctionExecutor created with ID: {}'.format(self.executor_id))

        self.data_cleaner = self.config['pywren'].get('data_cleaner', True)
        self.rabbitmq_monitor = self.config['pywren'].get('rabbitmq_monitor', False)

        if self.rabbitmq_monitor:
            if 'rabbitmq' in self.config and 'amqp_url' in self.config['rabbitmq']:
                self.rabbit_amqp_url = self.config['rabbitmq'].get('amqp_url')
            else:
                raise Exception("You cannot use rabbitmq_mnonitor since 'amqp_url'"
                                " is not present in configuration")

        storage_config = extract_storage_config(self.config)
        self.internal_storage = InternalStorage(storage_config)
        self.invoker = FunctionInvoker(self.config, self.executor_id, self.internal_storage)

        self.futures = []
        self.total_jobs = 0
        self.cleaned_jobs = set()
        self.last_call = None

    def _create_job_id(self, call_type):
        job_id = str(self.total_jobs).zfill(3)
        self.total_jobs += 1
        return '{}{}'.format(call_type, job_id)

    def call_async(self, func, data, extra_env=None, runtime_memory=None,
                   timeout=None, include_modules=[], exclude_modules=[]):
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
        job_id = self._create_job_id('A')
        self.last_call = 'call_async'

        runtime_meta = self.invoker.select_runtime(job_id, runtime_memory)

        job = create_map_job(self.config, self.internal_storage,
                             self.executor_id, job_id,
                             map_function=func,
                             iterdata=[data],
                             runtime_meta=runtime_meta,
                             runtime_memory=runtime_memory,
                             extra_env=extra_env,
                             include_modules=include_modules,
                             exclude_modules=exclude_modules,
                             execution_timeout=timeout)

        futures = self.invoker.run(job)
        self.futures.extend(futures)
        self._state = FunctionExecutor.State.Running

        return futures[0]

    def map(self, map_function, map_iterdata, extra_params=None, extra_env=None, runtime_memory=None,
            chunk_size=None, chunk_n=None, timeout=None, invoke_pool_threads=500,
            include_modules=[], exclude_modules=[]):
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
        job_id = self._create_job_id('M')
        self.last_call = 'map'

        runtime_meta = self.invoker.select_runtime(job_id, runtime_memory)

        job = create_map_job(self.config, self.internal_storage,
                             self.executor_id, job_id,
                             map_function=map_function,
                             iterdata=map_iterdata,
                             runtime_meta=runtime_meta,
                             runtime_memory=runtime_memory,
                             extra_params=extra_params,
                             extra_env=extra_env,
                             obj_chunk_size=chunk_size,
                             obj_chunk_number=chunk_n,
                             invoke_pool_threads=invoke_pool_threads,
                             include_modules=include_modules,
                             exclude_modules=exclude_modules,
                             execution_timeout=timeout)

        futures = self.invoker.run(job)
        self.futures.extend(futures)
        self._state = FunctionExecutor.State.Running

        return futures

    def map_reduce(self, map_function, map_iterdata, reduce_function, extra_params=None, extra_env=None,
                   map_runtime_memory=None, reduce_runtime_memory=None, chunk_size=None, chunk_n=None,
                   timeout=None, invoke_pool_threads=500, reducer_one_per_object=False,
                   reducer_wait_local=False, include_modules=[], exclude_modules=[]):
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
        map_job_id = self._create_job_id('M')
        self.last_call = 'map_reduce'

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
                                 invoke_pool_threads=invoke_pool_threads,
                                 include_modules=include_modules,
                                 exclude_modules=exclude_modules,
                                 execution_timeout=timeout)

        map_futures = self.invoker.run(map_job)
        self.futures.extend(map_futures)

        if reducer_wait_local:
            self.wait(fs=map_futures)

        reduce_job_id = map_job_id.replace('M', 'R')

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

        self.futures.extend(reduce_futures)

        for f in map_futures:
            f._produce_output = False

        self._state = FunctionExecutor.State.Running

        return map_futures + reduce_futures

    def wait(self, fs=None, throw_except=True, return_when=ALL_COMPLETED, download_results=False,
             timeout=None, THREADPOOL_SIZE=128, WAIT_DUR_SEC=1):
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
        futures = self.futures if not fs else fs
        if type(futures) != list:
            futures = [futures]
        if not futures:
            raise Exception('You must run the call_async(), map() or map_reduce(), or provide'
                            ' a list of futures before calling the wait()/get_result() method')

        if download_results:
            msg = 'ExecutorID {} - Getting results...'.format(self.executor_id)
        else:
            msg = 'ExecutorID {} - Waiting for functions to complete...'.format(self.executor_id)
        print(msg) if not self.log_level else logger.info(msg)

        if is_unix_system() and timeout is not None:
            logger.debug('Setting waiting timeout to {} seconds'.format(timeout))
            error_msg = 'Timeout of {} seconds exceeded waiting for function activations to finish'.format(timeout)
            signal.signal(signal.SIGALRM, partial(timeout_handler, error_msg))
            signal.alarm(timeout)

        pbar = None
        if not self.is_pywren_function and self._state == FunctionExecutor.State.Running \
           and not self.log_level:
            from tqdm.auto import tqdm

            if download_results:
                total_to_check = len([f for f in futures if not f.done])
            else:
                total_to_check = len([f for f in futures if not f.ready and not (f.ready or f.done)])

            if is_notebook():
                pbar = tqdm(bar_format='{n}/|/ {n_fmt}/{total_fmt}', total=total_to_check)  # ncols=800
            else:
                print()
                pbar = tqdm(bar_format='  {l_bar}{bar}| {n_fmt}/{total_fmt}  ', total=total_to_check, disable=False)

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

        except KeyboardInterrupt:
            if download_results:
                not_dones_call_ids = [(f.job_id, f.call_id) for f in futures if not f.done]
            else:
                not_dones_call_ids = [(f.job_id, f.call_id) for f in futures if not f.ready and not f.done]
            msg = ('ExecutorID {} - Cancelled - Total Activations not done: {}'
                   .format(self.executor_id, len(not_dones_call_ids)))
            if pbar:
                pbar.close()
            print(msg) if not self.log_level else logger.info(msg)
            self._state = FunctionExecutor.State.Error

        except Exception as e:
            self._state = FunctionExecutor.State.Error
            raise e

        finally:
            self.invoker.stop()
            if is_unix_system():
                signal.alarm(0)
            if pbar and not pbar.disable:
                pbar.close()
                if not is_notebook():
                    print()
            if self.data_cleaner and not self.is_pywren_function:
                self.clean()
            if not fs and self._state == FunctionExecutor.State.Error and is_notebook():
                del self.futures[len(self.futures)-len(futures):]

        if download_results:
            fs_done = [f for f in futures if f.done]
            fs_notdone = [f for f in futures if not f.done]
            self._state = FunctionExecutor.State.Done
        else:
            fs_done = [f for f in futures if f.ready or f.done]
            fs_notdone = [f for f in futures if not f.ready and not f.done]
            self._state = FunctionExecutor.State.Ready

        return fs_done, fs_notdone

    def get_result(self, fs=None, throw_except=True, timeout=None, THREADPOOL_SIZE=128, WAIT_DUR_SEC=1):
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
        result = []
        for f in fs_done:
            if fs and not f.futures and f._produce_output:
                # Process futures provided by the user
                result.append(f.result(throw_except=throw_except, internal_storage=self.internal_storage))
            elif not fs and not f.futures and f._produce_output and not f._read:
                # Process internally stored futures
                result.append(f.result(throw_except=throw_except, internal_storage=self.internal_storage))
                f._read = True

        logger.debug("ExecutorID {} Finished getting results".format(self.executor_id))

        if len(result) == 1 and self.last_call != 'map':
            return result[0]

        return result

    def create_execution_plots(self, dst_dir, dst_file_name, fs=None):
        """
        Creates timeline and histogram of the current execution in dst_dir.

        :param dst_dir: destination folder to save .png plots.
        :param dst_file_name: prefix name of the file.
        :param fs: list of futures.
        """
        ftrs = self.futures if not fs else fs
        if type(ftrs) != list:
            ftrs = [ftrs]
        ftrs_to_plot = [f for f in ftrs if (f.ready or f.done) and not f.error]

        if not ftrs_to_plot:
            logger.debug('ExecutorID {} - No futures ready to plot'.format(self.executor_id))
            return

        logging.getLogger('matplotlib').setLevel(logging.WARNING)
        from pywren_ibm_cloud.plots import create_timeline, create_histogram

        msg = 'ExecutorID {} - Creating execution plots'.format(self.executor_id)
        print(msg) if not self.log_level else logger.info(msg)

        call_status = [f._call_status for f in ftrs_to_plot]
        call_metadata = [f._call_metadata for f in ftrs_to_plot]

        create_timeline(dst_dir, dst_file_name, self.start_time, call_status, call_metadata, self.config['ibm_cos'])
        create_histogram(dst_dir, dst_file_name, self.start_time, call_status, self.config['ibm_cos'])

    def clean(self, fs=None, local_execution=True):
        """
        Deletes all the files from COS. These files include the function,
        the data serialization and the function invocation results.
        """
        futures = self.futures if not fs else fs
        if type(futures) != list:
            futures = [futures]
        if not futures:
            logger.debug('ExecutorID {} - No jobs to clean'.format(self.executor_id))
            return

        if not fs:
            present_jobs = {(f.executor_id, f.job_id) for f in futures
                            if (f.done or not f._produce_output)
                            and f.executor_id.count('/') == 1}
        else:
            present_jobs = {(f.executor_id, f.job_id) for f in futures
                            if f.executor_id.count('/') == 1}

        jobs_to_clean = present_jobs - self.cleaned_jobs

        if jobs_to_clean:
            msg = "ExecutorID {} - Cleaning temporary data".format(self.executor_id)
            print(msg) if not self.log_level else logger.info(msg)

        for executor_id, job_id in jobs_to_clean:
            storage_bucket = self.config['pywren']['storage_bucket']
            storage_prerix = '/'.join([JOBS_PREFIX, executor_id, job_id])

            if local_execution:
                # 1st case: Not background. The main code waits until the cleaner finishes its execution.
                # It is not ideal for performance tests, since it can take long time to complete.
                # clean_os_bucket(storage_bucket, storage_prerix, self.internal_storage)

                # 2nd case: Execute in Background as a subprocess. The main program does not wait for its completion.
                storage_config = json.dumps(self.internal_storage.get_storage_config())
                storage_config = storage_config.replace('"', '\\"')

                cmdstr = ('{} -c "from pywren_ibm_cloud.storage.utils import clean_bucket; \
                                  clean_bucket(\'{}\', \'{}\', \'{}\')"'.format(sys.executable,
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

        self.cleaned_jobs.update(jobs_to_clean)
