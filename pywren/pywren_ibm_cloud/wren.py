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
import sys
import os
import signal
from multiprocessing.pool import ThreadPool
import pywren_ibm_cloud as pywren
import pywren_ibm_cloud.invokers as invokers
import pywren_ibm_cloud.wrenconfig as wrenconfig
from pywren_ibm_cloud.storage import storage
from pywren_ibm_cloud.storage.cleaner import clean_os_bucket
from pywren_ibm_cloud.executor import Executor
from pywren_ibm_cloud.wait import wait, ALL_COMPLETED
from pywren_ibm_cloud.wrenutil import timeout_handler
from pywren_ibm_cloud import wrenlogging

import json

logger = logging.getLogger(__name__)

JOB_MAX_RUNTIME = 600


class ExecutorState(enum.Enum):
    new = 1
    single_call = 2
    map = 3
    map_reduce = 4
    success = 5
    closed = 6
    error = 7


class ibm_cf_executor(object):
    
    def __init__(self, config=None, runtime=None, log_level=None, job_max_runtime=JOB_MAX_RUNTIME):
        """
        Initialize and return an executor class.
    
        :param config: Settings passed in here will override those in `pywren_config`. Default None.
        :param runtime: Runtime name to use. Default None.
        :param job_max_runtime: Max time per lambda. Default 300
        :return `executor` object.
    
        Usage
          >>> import pywren
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
        
        self._openwhisk = False
        if any([k.startswith('__OW_') for k in os.environ.keys()]):
            # OpenWhisk execution
            self._openwhisk = True
            wrenlogging.ow_config(logging.INFO)
    
        self.runtime = self.config['ibm_cf']['action_name']
    
        ibm_cf_config = self.config['ibm_cf']
        invoker = invokers.IBMCloudFunctionsInvoker(ibm_cf_config)
        self.storage_config = wrenconfig.extract_storage_config(self.config)
        self.storage_handler = storage.Storage(self.storage_config)
        self.executor = Executor(invoker, self.config, self.storage_handler, job_max_runtime)
        self.executor_id = self.executor.executor_id

        self.futures = None
        self.reduce_future = None
        
        log_msg='IBM Cloud Functions executor created with ID {}'.format(self.executor_id)
        logger.info(log_msg)
        if(logger.getEffectiveLevel() == logging.WARNING):
            print(log_msg)

    def call_async(self, func, data, extra_env=None, extra_meta=None):
        """
        For run one function execution
        :param func: the function to map over the data
        :param data: input data
        :param extra_env: Additional environment variables for lambda environment. Default None.
        :param extra_meta: Additional metadata to pass to lambda. Default None.

        Usage
          >>> import pywren
          >>> pw = pywren.ibm_cf_executor()
          >>> future = pw.call_async(foo, data)
        """
        if not self._state == ExecutorState.new:
            raise Exception('You cannot run pw.call_async() in the current state,'
                            ' create a new pywren.ibm_cf_executor() instance.')
        self._state = ExecutorState.single_call
        self.futures = self.executor.call_async(func, data, extra_env, extra_meta)[0]
        
        return self.futures

    def map(self, func, iterdata, extra_env=None, extra_meta=None, 
            remote_invocation=False, invoke_pool_threads=128, data_all_as_one=True,
            overwrite_invoke_args=None, exclude_modules=None):
        """
        :param func: the function to map over the data
        :param iterdata: An iterable of input data
        :param extra_env: Additional environment variables for lambda environment. Default None.
        :param extra_meta: Additional metadata to pass to lambda. Default None.
        :param invoke_pool_threads: Number of threads to use to invoke.
        :param data_all_as_one: upload the data as a single object. Default True
        :param overwrite_invoke_args: Overwrite other args. Mainly used for testing.
        :param exclude_modules: Explicitly keep these modules from pickled dependencies.
        :return: A list with size `len(iterdata)` of futures for each job
        :rtype: list of futures.

        Usage
          >>> import pywren
          >>> pw = pywren.ibm_cf_executor()
          >>> futures = pw.map(foo, data_list)
        """
        if not self._state == ExecutorState.new:
            raise Exception('You cannot run pw.map() in the current state.'
                            ' Create a new pywren.ibm_cf_executor() instance.')

        def remote_invoker(iterdata):
            pw = pywren.ibm_cf_executor()
            return pw.map(func, iterdata)

        if type(iterdata) == list and len(iterdata) > 1 and remote_invocation:
            map_func = remote_invoker
            map_iterdata = [[iterdata, ]]
        else:
            remote_invocation = False
            map_func = func
            map_iterdata = iterdata

        self.futures = self.executor.map(func=map_func, iterdata=map_iterdata,
                                         extra_env=extra_env, extra_meta=extra_meta,
                                         invoke_pool_threads=invoke_pool_threads,
                                         data_all_as_one=data_all_as_one,
                                         overwrite_invoke_args=overwrite_invoke_args,
                                         exclude_modules=exclude_modules,
                                         original_func_name=func.__name__)
        
        if remote_invocation:
            msg='Executor ID {} Getting remote invocations'.format(self.executor_id)
            logger.info(msg)
            if(logger.getEffectiveLevel() == logging.WARNING):
                print(msg)  
            self.futures = self.futures[0].result(storage_handler=self.storage_handler)
        
        self._state = ExecutorState.map
        
        if type(self.futures) == list and len(self.futures) == 1:
            self.futures = self.futures[0]
            self._state = ExecutorState.single_call
        
        return self.futures

    def map_reduce(self, map_function, map_iterdata, reduce_function,
                   chunk_size=64*1024**2, reducer_one_per_object = False,
                   reducer_wait_local=True, throw_except=True,
                   extra_env=None, extra_meta=None):
        """
        Map the map_function over the data and apply the reduce_function across all futures.
        This method is executed all within CF.
        :param map_function: the function to map over the data
        :param reduce_function:  the function to reduce over the futures
        :param map_iterdata:  the function to reduce over the futures
        :param chunk_size: the size of the data chunks
        :param extra_env: Additional environment variables for lambda environment. Default None.
        :param extra_meta: Additional metadata to pass to lambda. Default None.
        :return: A list with size `len(map_iterdata)` of futures for each job
        
        Usage
          >>> import pywren
          >>> pw = pywren.ibm_cf_executor()
          >>> pw.map_reduce(foo, bar, data_list)
        """
        
        if not self._state == ExecutorState.new:
            raise Exception('You cannot run pw.map_reduce() in the current state.'
                            ' Create a new pywren.ibm_cf_executor() instance.')
           
        self.futures = self.executor.map_reduce(map_function, map_iterdata,
                                                reduce_function, chunk_size,
                                                reducer_one_per_object,
                                                reducer_wait_local,
                                                throw_except, extra_env, extra_meta)
        
        self._state = ExecutorState.map_reduce
        
        if type(self.futures) == list and len(self.futures) == 1:
            self.futures = self.futures[0]
            self._state = ExecutorState.single_call
        if type(self.futures) != list:
            self._state = ExecutorState.single_call

        return self.futures

    def wait(self, throw_except=True, verbose=True, return_when=ALL_COMPLETED,
             THREADPOOL_SIZE=64, WAIT_DUR_SEC=4):
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
          >>> import pywren
          >>> pw = pywren.ibm_cf_executor()
          >>> pw.map(foo, data_list)
          >>> dones, not_dones = pw.wait()
          >>> # not_dones should be an empty list.
          >>> results = [f.result() for f in dones]
        """
        if not self._state == ExecutorState.map or not self._state == ExecutorState.map_reduce:
            raise Exception('You must run pw.map() or pw.map_reduce() before call pw.wait()')
        
        return wait(self.futures, self.executor_id, self.storage_handler,
                    throw_except, verbose, return_when, THREADPOOL_SIZE, WAIT_DUR_SEC)


    def get_result(self, throw_except=True, verbose=False, timeout=JOB_MAX_RUNTIME):
        """
        For get PyWren results
        :param throw_except: Reraise exception if call raised. Default true.
        :param verbose: Shows some information prints.
        :return: The result of the future/s

        Usage
          >>> import pywren
          >>> pw = pywren.ibm_cf_executor()
          >>> pw.call_async(foo, data)
          >>> result = pw.get_result()
        """
        if self._state == ExecutorState.single_call:
            return self._get_result(throw_except=throw_except, verbose=verbose, timeout=timeout)
        else:
            return self._get_all_results(throw_except=throw_except, verbose=verbose, timeout=timeout)

    def _get_result(self, throw_except=True, verbose=False, timeout=JOB_MAX_RUNTIME):
        """
        For get one function execution (future) result
        :param throw_except: Reraise exception if call raised. Default true.
        :param verbose: Shows some information prints.
        :return: The result of the call_async future

        Usage
          >>> import pywren
          >>> pw = pywren.ibm_cf_executor()
          >>> pw.call_async(foo, data)
          >>> result = pw._get_result()
        """
        if self._state == ExecutorState.new:
            raise Exception('You must run pw.call_async(), or pw.map() '
                            'or pw.map_reduce() before call pw.get_result()')
        
        msg='Executor ID {} Getting result'.format(self.executor_id)
        logger.info(msg)
        if(logger.getEffectiveLevel() == logging.WARNING):
            print(msg)            
       
        signal.signal(signal.SIGALRM, timeout_handler) 
        signal.alarm(timeout)
        
        try:
            if not verbose:
                import tqdm
                print()
                pbar = tqdm.tqdm(bar_format='  {l_bar}{bar}| {n_fmt}/{total_fmt}  ',
                                 total=1, disable=False)
            while not self.futures.done:
                result = self.futures.result(storage_handler=self.storage_handler,
                                             throw_except=throw_except, 
                                             verbose=verbose)
                signal.alarm(timeout)
                
            if not verbose:
                pbar.update(1)
                pbar.close()
                print()

            self._state = ExecutorState.success

        except (TimeoutError, IndexError):
            if not verbose:
                if pbar:
                    pbar.close()
                    print() 
            msg=('Executor ID {} Raised timeout of {} seconds getting the '
                 'result from Activation ID {}'.format(self.executor_id, timeout,
                                                       self.futures.activation_id))
            logger.info(msg)
            if(logger.getEffectiveLevel() == logging.WARNING):
                print(msg)
            self._state = ExecutorState.error
            result = None
        
        except KeyboardInterrupt:
            if not verbose:
                if pbar:
                    pbar.close()
                    print() 
            msg='Executor ID {} Cancelled'.format(self.executor_id)
            logger.info(msg)
            if(logger.getEffectiveLevel() == logging.WARNING):
                print(msg)
            exit()
        
        finally:
            signal.alarm(0)
            if not verbose:
                if pbar:
                    pbar.close() 
            self._clean()
            print()

        return result

    def _get_all_results(self, throw_except=True, verbose=False,
                         timeout=JOB_MAX_RUNTIME, THREADPOOL_SIZE=64,
                         WAIT_DUR_SEC=3):
        """
        Take in a list of futures, call result on each one individually
        by using a threadpool, and return those results. Useful to fetch
        the results as they are produced.
    
        :param throw_except: Reraise exception if call raised. Default True.
        :param verbose: Show results (True) or progress bar (False). Default False.
        :return: A list of the results of each futures
        :rtype: list
    
        Usage
          >>> import pywren
          >>> pw = pywren.ibm_cf_executor()
          >>> pw.map(foo, data)
          >>> results = pw._get_all_results()    
        """
        if self._state == ExecutorState.new:
            raise Exception('You must run pw.map() or pw.map_reduce() '
                            'before call pw.get_all_results()')
        
        msg='Executor ID {} Getting results'.format(self.executor_id)
        logger.info(msg)
        if(logger.getEffectiveLevel() == logging.WARNING):
            print(msg)

        def timeout_handler(signum, frame):
            raise TimeoutError()

        signal.signal(signal.SIGALRM, timeout_handler) 
        signal.alarm(timeout)
        
        try: 
            pool = ThreadPool(THREADPOOL_SIZE)
            
            def fetch_future_results(f):
                f.result(storage_handler=self.storage_handler,
                         throw_except=throw_except, verbose=verbose)
                return f
            
            N = len(self.futures)
            if not verbose:
                import tqdm
                print()
                pbar = tqdm.tqdm(bar_format='  {l_bar}{bar}| {n_fmt}/{total_fmt}  ',
                                 total=N, disable=False)
    
            callids_done_in_callset = set()
            call_ids = set()
            
            while len(callids_done_in_callset)<N:
                sleep = WAIT_DUR_SEC-((len(callids_done_in_callset)/N)*WAIT_DUR_SEC)
                time.sleep(sleep)
                
                current_call_ids = set([(f.callgroup_id, f.call_id) for f in self.futures])
                call_ids = set(self.storage_handler.get_callset_status(self.executor_id))
                call_ids_to_check = call_ids.intersection(current_call_ids)
    
                not_done_call_ids = call_ids_to_check.difference(callids_done_in_callset)
    
                still_not_done_futures = [f for f in self.futures if ((f.callgroup_id, f.call_id) in not_done_call_ids)]
                
                if verbose and still_not_done_futures:
                    pool.map(fetch_future_results, still_not_done_futures)
                elif still_not_done_futures:
                    futures = pool.map(fetch_future_results, still_not_done_futures)            
                    for f in futures:
                        if f.done:
                            pbar.update(1)
                    pbar.refresh()
    
                callids_done_in_callset.update([(f.callgroup_id, f.call_id) for f in still_not_done_futures if f.done])
    
            if not verbose:
                pbar.close()
                print()
            pool.close()
            self._state = ExecutorState.success
        
        except (TimeoutError, IndexError):
            if not verbose:
                if pbar:
                    pbar.close()
                    print() 
            not_dones_activation_ids = set([f.activation_id for f in self.futures if not f.done])
            msg='Executor ID {} Raised timeout of {} seconds getting results \nActivations not done: {}'.format(self.executor_id, timeout, not_dones_activation_ids)
            logger.info(msg)
            if(logger.getEffectiveLevel() == logging.WARNING):
                print(msg)
            self._state = ExecutorState.error
        
        except KeyboardInterrupt:
            if not verbose:
                if pbar:
                    pbar.close()
                    print()
            not_dones_activation_ids = [f.activation_id for f in self.futures if not f.done]
            msg='Executor ID {} Cancelled  \nActivations not done: {}'.format(self.executor_id, not_dones_activation_ids)
            logger.info(msg)
            if(logger.getEffectiveLevel() == logging.WARNING):
                print(msg)
            exit()
        
        finally:
            if not verbose:
                if pbar:
                    pbar.close()
            signal.alarm(0)
            self._clean()
            print()
        
        results = [f.result(throw_except=throw_except) for f in self.futures if f.done]
        
        return results

    def _clean(self, local_execution=True):
        """
        Deletes all the files from COS. These files include the function,
        the data serialization and the function invocation results.
        """
        storage_bucket = self.storage_config['storage_bucket']
        storage_prerix = self.storage_config['storage_prefix']
        storage_prerix = os.path.join(storage_prerix, self.executor_id)
        
        msg="Executor ID {} Cleaning partial results from PyWren bucket '{}'".format(self.executor_id, storage_bucket)
        logger.info(msg)
        if(logger.getEffectiveLevel() == logging.WARNING):
            print(msg)
            
        if local_execution:
            storage_config = json.dumps(self.storage_handler.get_storage_config())
            storage_config = storage_config.replace('"', '\\"')
            cmdstr = ("python3 -c 'from pywren_ibm_cloud.storage.cleaner import clean_bucket; \
                                   clean_bucket(\"{}\", \"{}\", \"{}\")'".format(storage_bucket,
                                                                                 storage_prerix,
                                                                                 storage_config))
            os.popen(cmdstr)
        else:
            extra_env = {'NOT_STORE_RESULTS': 'True'}
            sys.stdout = open(os.devnull, 'w')
            self.executor.call_async(clean_os_bucket, [storage_bucket, storage_prerix], extra_env=extra_env)
            sys.stdout = sys.__stdout__
        
        self._state = ExecutorState.closed
