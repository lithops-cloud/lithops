#
# (C) Copyright IBM Corp. 2020
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

from lithops.executors import FunctionExecutor
from lithops.executors import LocalhostExecutor
from lithops.executors import ServerlessExecutor
from lithops.executors import StandaloneExecutor
from lithops.version import __version__

name = "lithops"


def ibm_cf_executor(config=None, runtime=None, runtime_memory=None,
                    workers=None, storage_backend=None,
                    rabbitmq_monitor=None, remote_invoker=None, log_level=None):
    """
    Function executor for IBM Cloud Functions
    """
    compute_backend = 'ibm_cf'
    return ServerlessExecutor(
        config=config, runtime=runtime, runtime_memory=runtime_memory,
        workers=workers, backend=compute_backend,
        storage=storage_backend,
        rabbitmq_monitor=rabbitmq_monitor,
        remote_invoker=remote_invoker,
        log_level=log_level
    )


def knative_executor(config=None, runtime=None, runtime_memory=None, workers=None,
                     storage_backend=None,
                     rabbitmq_monitor=None, remote_invoker=None, log_level=None):
    """
    Function executor for Knative
    """
    compute_backend = 'knative'
    return ServerlessExecutor(
        config=config, runtime=runtime, runtime_memory=runtime_memory,
        workers=workers, backend=compute_backend,
        storage=storage_backend,
        rabbitmq_monitor=rabbitmq_monitor,
        remote_invoker=remote_invoker,
        log_level=log_level
    )


def function_executor(type=None, config=None, backend=None, storage=None,
                      runtime=None, runtime_memory=None, workers=None,
                      rabbitmq_monitor=None, remote_invoker=None, log_level=None):
    """
    Generic function executor
    """
    return FunctionExecutor(
        type=type,
        config=config,
        runtime=runtime,
        runtime_memory=runtime_memory,
        workers=workers,
        backend=backend,
        storage=storage,
        rabbitmq_monitor=rabbitmq_monitor,
        remote_invoker=remote_invoker,
        log_level=log_level
    )


def local_executor(config=None, workers=None,
                   storage_backend=None,
                   rabbitmq_monitor=None,
                   log_level=None):
    """
    Localhost function executor
    """
    return LocalhostExecutor(
        config=config, workers=workers,
        storage=storage_backend,
        rabbitmq_monitor=rabbitmq_monitor,
        log_level=log_level
    )


def code_engine_executor(config=None, runtime=None, runtime_memory=None,
                         workers=None,  storage_backend=None,
                         rabbitmq_monitor=None, log_level=None):
    """
    Function executor for Code Engine
    """
    compute_backend = 'code_engine'
    return ServerlessExecutor(
        config=config, runtime=runtime, runtime_memory=runtime_memory,
        workers=workers, backend=compute_backend,
        storage=storage_backend,
        rabbitmq_monitor=rabbitmq_monitor,
        remote_invoker=True,
        log_level=log_level
    )
