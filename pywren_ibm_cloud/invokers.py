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
import time
import logging
import random
from pywren_ibm_cloud.libs.ibm_cf.cf_connector import CloudFunctions
from pywren_ibm_cloud.utils import create_action_name, create_runtime_name
from pywren_ibm_cloud.wrenconfig import extract_cf_config

logger = logging.getLogger(__name__)


class IBMCloudFunctionsInvoker:

    def __init__(self, config):
        self.log_level = os.getenv('PYWREN_LOG_LEVEL')
        cf_config = extract_cf_config(config)
        self.namespace = cf_config['namespace']
        self.endpoint = cf_config['endpoint'].replace('http:', 'https:')
        self.runtime = cf_config['runtime']
        self.runtime_memory = int(cf_config['runtime_memory'])
        self.runtime_timeout = int(cf_config['runtime_timeout'])

        runtime_name = create_runtime_name(self.runtime, self.runtime_memory)
        self.action_name = create_action_name(runtime_name)

        self.invocation_retry = config['pywren']['invocation_retry']
        self.retry_sleeps = config['pywren']['retry_sleeps']
        self.retries = config['pywren']['retries']

        self.client = CloudFunctions(cf_config)

        msg = 'IBM Cloud Functions init for'
        logger.info('{} namespace: {}'.format(msg, self.namespace))
        logger.info('{} host: {}'.format(msg, self.endpoint))
        logger.info('{} Runtime: {} - {}MB'.format(msg, self.runtime, self.runtime_memory))

        if not self.log_level:
            print("{} Namespace: {}".format(msg, self.namespace))
            print("{} Host: {}".format(msg, self.endpoint))
            print('{} Runtime: {} - {}MB'.format(msg, self.runtime, self.runtime_memory), end=' ')

    def invoke(self, payload):
        """
        Invoke -- return information about this invocation
        """
        act_id = self.client.invoke(self.action_name, payload)
        attempts = 1

        while not act_id and self.invocation_retry and attempts < self.retries:
            attempts += 1
            selected_sleep = random.choice(self.retry_sleeps)
            exec_id = payload['executor_id']
            call_id = payload['call_id']

            log_msg = ('Executor ID {} Function {} - Invocation failed - retry {} in {} seconds'.format(exec_id, call_id, attempts, selected_sleep))
            logger.debug(log_msg)

            time.sleep(selected_sleep)
            act_id = self.client.invoke(self.action_name, payload)

        return act_id

    def config(self):
        """
        Return config dict
        """
        return {'runtime': self.runtime,
                'runtime_memory': self.runtime_memory,
                'runtime_timeout': self.runtime_timeout,
                'namespace': self.namespace,
                'endpoint': self.endpoint}
