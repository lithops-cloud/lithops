import os
import logging
from pywren_ibm_cloud.utils import format_action_name
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

    def create_runtime(self, runtime_name, runtime_memory):
        pass

    def invoke(self, runtime_name, runtime_memory, payload):
        """
        Invoke -- return information about this invocation
        """
        action_name = format_action_name(runtime_name, runtime_memory)
        return self.cf_client.invoke(self.package, action_name, payload)
