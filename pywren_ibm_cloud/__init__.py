#
# (C) Copyright IBM Corp. 2019
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

import tempfile
from pywren_ibm_cloud.executor import FunctionExecutor
from pywren_ibm_cloud.version import __version__

name = "pywren_ibm_cloud"


def ibm_cf_executor(config=None, runtime=None, runtime_memory=None,
                    workers=None, region=None, storage_backend=None,
                    storage_backend_region=None, rabbitmq_monitor=None,
                    remote_invoker=None, log_level=None):
    """
    Function executor for IBM Cloud Functions
    """
    compute_backend = 'ibm_cf'
    return FunctionExecutor(
        config=config, runtime=runtime, runtime_memory=runtime_memory,
        workers=workers, compute_backend=compute_backend,
        compute_backend_region=region,
        storage_backend=storage_backend,
        storage_backend_region=storage_backend_region,
        rabbitmq_monitor=rabbitmq_monitor,
        remote_invoker=remote_invoker,
        log_level=log_level
    )


def knative_executor(config=None, runtime=None, runtime_memory=None, workers=None,
                     region=None, storage_backend=None, storage_backend_region=None,
                     rabbitmq_monitor=None, remote_invoker=None, log_level=None):
    """
    Function executor for Knative
    """
    compute_backend = 'knative'
    return FunctionExecutor(
        config=config, runtime=runtime, runtime_memory=runtime_memory,
        workers=workers, compute_backend=compute_backend,
        compute_backend_region=region,
        storage_backend=storage_backend,
        storage_backend_region=storage_backend_region,
        rabbitmq_monitor=rabbitmq_monitor,
        remote_invoker=remote_invoker,
        log_level=log_level
    )


def openwhisk_executor(config=None, runtime=None, runtime_memory=None,
                       workers=None, storage_backend=None,
                       storage_backend_region=None, rabbitmq_monitor=None,
                       remote_invoker=None, log_level=None):
    """
    Function executor for OpenWhisk
    """
    compute_backend = 'openwhisk'
    return FunctionExecutor(
        config=config, runtime=runtime, runtime_memory=runtime_memory,
        workers=workers, compute_backend=compute_backend,
        storage_backend=storage_backend,
        storage_backend_region=storage_backend_region,
        rabbitmq_monitor=rabbitmq_monitor,
        remote_invoker=remote_invoker,
        log_level=log_level
    )


def function_executor(config=None, runtime=None, runtime_memory=None,
                      workers=None, backend=None, region=None,
                      storage_backend=None, storage_backend_region=None,
                      rabbitmq_monitor=None, remote_invoker=None, log_level=None):
    """
    Generic function executor
    """
    return FunctionExecutor(
        config=config, runtime=runtime,
        runtime_memory=runtime_memory,
        workers=workers,
        compute_backend=backend,
        compute_backend_region=region,
        storage_backend=storage_backend,
        storage_backend_region=storage_backend_region,
        rabbitmq_monitor=rabbitmq_monitor,
        remote_invoker=remote_invoker,
        log_level=log_level
    )


def local_executor(config=None, workers=None, storage_backend=None,
                   storage_backend_region=None, rabbitmq_monitor=None,
                   log_level=None):
    """
    Localhost function executor
    """
    compute_backend = 'localhost'

    if storage_backend is None:
        storage_backend = 'localhost'

    return FunctionExecutor(
        config=config, workers=workers,
        compute_backend=compute_backend,
        storage_backend=storage_backend,
        storage_backend_region=storage_backend_region,
        rabbitmq_monitor=rabbitmq_monitor,
        log_level=log_level
    )


def docker_executor(config=None, runtime=None, workers=None,
                    storage_backend=None, storage_backend_region=None,
                    rabbitmq_monitor=None, log_level=None):
    """
    Localhost function executor
    """
    compute_backend = 'docker'

    if storage_backend is None:
        storage_backend = 'localhost'

    return FunctionExecutor(
        config=config, runtime=runtime,
        workers=workers,
        compute_backend=compute_backend,
        storage_backend=storage_backend,
        storage_backend_region=storage_backend_region,
        rabbitmq_monitor=rabbitmq_monitor,
        log_level=log_level
    )
