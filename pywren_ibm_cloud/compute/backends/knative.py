import os
import ssl
import json
import time
import base64
import logging
import requests
import http.client
from urllib.parse import urlparse
from pywren_ibm_cloud.version import __version__
from pywren_ibm_cloud.utils import is_cf_cluster
from pywren_ibm_cloud.libs.ibm.cloudfunctions_client import CloudFunctionsClient

logger = logging.getLogger(__name__)


class KnativeComputeBackend:
    """
    A wrap-up around Knative Serving APIs.
    """

    def __init__(self, knative_config):
        self.log_level = os.getenv('PYWREN_LOG_LEVEL')
        self.name = 'knative'
        self.knative_config = knative_config
        self.endpoint = self.knative_config['endpoint']
        self.serving_host = self.knative_config['host']
        self.package = 'pywren_v'+__version__
        self.is_cf_cluster = is_cf_cluster()

        log_msg = 'PyWren v{} init for Knative Serving - IP: {} - Service: {}'.format(__version__, self.endpoint, self.serving_host)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)

        self.headers = {
            'content-type': 'application/json',
            'Host': self.serving_host
        }

        logger.debug('Knative init for host: {}'.format(self.endpoint))
        logger.debug('Knative init for service: {}'.format(self.endpoint))

    def create_runtime(self, docker_image_name, memory, code=None, is_binary=True, timeout=300000):
        pass

    def delete_runtime(self, docker_image_name, memory):
       pass 

    def delete_all_runtimes(self):
        pass

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes deployed in the IBM CF service
        return: list of tuples [docker_image_name, memory]
        """
        runtimes = []
        return runtimes

    def invoke(self, runtime_name, runtime_memory, payload):
        """
        Invoke -- return information about this invocation
        """
        exec_id = payload['executor_id']
        call_id = payload['call_id']
        callgroup_id = payload['callgroup_id']
        start = time.time()
        try:
            conn = http.client.HTTPConnection(self.endpoint)
            conn.request("POST", '',
                         body=json.dumps(payload),
                         headers=self.headers)
            resp = conn.getresponse()
            resp_status = resp.status
            data = json.loads(resp.read().decode("utf-8"))
            conn.close()
            return payload['executor_id'] + payload['callgroup_id'] + payload['call_id']
        except Exception as e:
            if not is_cf_cluster:
                conn.close()
            log_msg = ('ExecutorID {} - Function {} invocation failed: {}'.format(exec_id, call_id, str(e)))
            logger.debug(log_msg)
            if self_invoked:
                return None
            return self.invoke(package, action_name, payload, is_cf_cluster, self_invoked=True)

        roundtrip = time.time() - start
        resp_time = format(round(roundtrip, 3), '.3f')
        if resp_status == 200:
            log_msg = ('ExecutorID {} - Function {} invocation done! ({}s) '
                       .format(exec_id, call_id, resp_time))
            logger.debug(log_msg)
            return exec_id + callgroup_id + call_id
        else:
            logger.debug(data)
            if resp_status == 401:
                raise Exception('Unauthorized - Invalid API Key')
            elif resp_status == 404:
                raise Exception('Not Found')
            elif resp_status == 429:
                # Too many concurrent requests in flight
                return None
            else:
                raise Exception(resp_status)

    def invoke_with_result(self, runtime_name, runtime_memory, payload={}):
        """
        Invoke waiting for a result -- return information about this invocation
        """
        pass

    def get_runtime_key(self, runtime_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        #action_name = self._format_action_name(runtime_name, runtime_memory)
        runtime_key = runtime_name#os.path.join(self.name, self.region, self.namespace, action_name)

        return runtime_key
