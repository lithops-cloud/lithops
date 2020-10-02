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
from lithops.executors import ServerlessExecutor, StandaloneExecutor, LocalhostExecutor
from lithops.version import __version__

name = "lithops"


def local_executor(config=None, runtime=None, workers=None, storage=None,
                   storage_region=None, rabbitmq_monitor=None, log_level=None):

    if storage is None:
        storage = 'localhost'

    return LocalhostExecutor(
        config=config, runtime=runtime,
        workers=workers, storage=storage,
        storage_region=storage_region,
        rabbitmq_monitor=rabbitmq_monitor,
        log_level=log_level
    )


def serverless_executor(config=None, backend=None, runtime=None,
                        runtime_memory=None, workers=None, region=None,
                        storage=None, storage_region=None, rabbitmq_monitor=None,
                        remote_invoker=None, log_level=None):

    return ServerlessExecutor(
        config=config, runtime=runtime,
        runtime_memory=runtime_memory,
        workers=workers, backend=backend,
        region=region, storage=storage,
        storage_region=storage_region,
        rabbitmq_monitor=rabbitmq_monitor,
        remote_invoker=remote_invoker,
        log_level=log_level
    )


def standalone_executor(config=None, backend=None, region=None,
                        runtime=None, cpu=None, memory=None, instances=None,
                        storage=None, storage_region=None, workers=None,
                        rabbitmq_monitor=None, log_level=None):

    return StandaloneExecutor(
        config=config, runtime=runtime,
        backend=backend, region=region,
        workers=workers, cpu=cpu, memory=memory,
        instances=instances, storage=storage,
        storage_region=storage_region,
        rabbitmq_monitor=rabbitmq_monitor,
        log_level=log_level
    )


function_executor = serverless_executor
