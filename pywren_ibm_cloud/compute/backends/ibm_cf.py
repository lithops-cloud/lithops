import os
import logging
from pywren_ibm_cloud.libs.ibm.cloudfunctions_client import CloudFunctionsClient
from pywren_ibm_cloud.version import __version__

logger = logging.getLogger(__name__)


class IbmCfComputeBackend:
    """
    A wrap-up around IBM Cloud Functions APIs.
    """

    def __init__(self, ibm_cf_config):
        self.log_level = os.getenv('PYWREN_LOG_LEVEL')
        self.ibm_cf_config = ibm_cf_config
        self.package = 'pywren_v'+__version__
        self.cf_client = CloudFunctionsClient(self.ibm_cf_config)

        self.region = ibm_cf_config['endpoint'].split('//')[1].split('.')[0]
        self.namespace = ibm_cf_config['namespace']
        log_msg = 'PyWren v{} init for IBM Cloud Functions - Namespace: {} - Region: {}'.format(__version__, self.namespace, self.region)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)

    def _format_action_name(self, runtime_name, runtime_memory):
        runtime_name = runtime_name.replace('/', '_').replace(':', '_')
        return '{}_{}MB'.format(runtime_name, runtime_memory)

    def create_runtime(self, runtime_name, runtime_memory, internal_storage):
        print('----------------')

    def invoke(self, runtime_name, runtime_memory, payload):
        """
        Invoke -- return information about this invocation
        """
        action_name = self._format_action_name(runtime_name, runtime_memory)
        return self.cf_client.invoke(self.package, action_name, payload)

    def get_runtime_info(self, runtime_name, runtime_memory, internal_storage):
        action_name = self._format_action_name(runtime_name, runtime_memory)
        runtime_key = os.path.join(self.region, self.namespace, action_name)
        runtime_meta = internal_storage.get_runtime_info(runtime_key)

        return runtime_meta
