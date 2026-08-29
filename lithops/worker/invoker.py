#
# (C) Copyright Cloudlab URV 2020
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
import json
import time
import logging
from types import SimpleNamespace
from typing import Any, Dict

from lithops.serverless import ServerlessHandler
from lithops.monitor import JobMonitor
from lithops.storage import InternalStorage
from lithops.config import extract_serverless_config, extract_storage_config
from lithops.invokers import FaaSInvoker
from lithops.utils import MONITORING_QUEUES_ENV, monitoring_queues


logger = logging.getLogger(__name__)


def function_invoker(job_payload: Dict[str, Any]) -> None:
    """
    Entry point of the remote invoker: invokes a whole job from a worker,
    instead of from the client
    """
    config = job_payload['config']
    job = SimpleNamespace(**job_payload['job'])

    os.environ.update({
        'LITHOPS_WORKER': 'True',
        'PYTHONUNBUFFERED': 'True',
        '__LITHOPS_SESSION_ID': job.job_key,
        # The job this invoker spawns reports to the queues of the client, and
        # an executor created here extends that chain rather than replacing it
        MONITORING_QUEUES_ENV: json.dumps(
            monitoring_queues(job.executor_id)
        ),
    })

    backend = config['lithops']['backend']
    config[backend]['invoke_pool_threads'] = 128

    storage_config = extract_storage_config(config)
    internal_storage = InternalStorage(storage_config)

    serverless_config = extract_serverless_config(config)
    compute_handler = ServerlessHandler(serverless_config, storage_config)

    monitoring_backend = config['lithops']['monitoring'].lower()
    job_monitor = JobMonitor(
        executor_id=job.executor_id,
        internal_storage=internal_storage,
        backend=monitoring_backend,
        config=config.get(monitoring_backend)
    )

    invoker = FaaSRemoteInvoker(
        config,
        job.executor_id,
        internal_storage,
        compute_handler,
        job_monitor
    )
    invoker.run_job(job)


class FaaSRemoteInvoker(FaaSInvoker):
    """
    Module responsible to perform the invocations against the serverless
    compute backend
    """

    def run_job(self, job: SimpleNamespace) -> None:
        """
        Invokes every task of the job and waits until they are all submitted
        """
        futures = self._run_job(job)
        self.job_monitor.start(
            fs=futures,
            job_id=job.job_id,
            chunksize=job.chunksize,
            generate_tokens=True
        )

        # stop() drops whatever is still pending, so wait until the async
        # invokers have picked every chunk up before stopping them
        while self.pending_calls_q.qsize() > 0:
            time.sleep(1)

        self.job_monitor.stop()
        # Waits for the invocations still in flight, which this worker must not
        # be frozen in the middle of
        self.stop(wait=True)

        logger.info('Remote Invoker Finished')
