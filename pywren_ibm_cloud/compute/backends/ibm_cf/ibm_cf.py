import os
import logging
import zipfile
from pywren_ibm_cloud.version import __version__
from pywren_ibm_cloud.utils import is_cf_cluster
from pywren_ibm_cloud.libs.ibm.cloudfunctions_client import CloudFunctionsClient

logger = logging.getLogger(__name__)


class IbmCfComputeBackend:
    """
    A wrap-up around IBM Cloud Functions backend.
    """

    def __init__(self, ibm_cf_config):
        self.log_level = os.getenv('PYWREN_LOG_LEVEL')
        self.name = 'ibm_cf'
        self.ibm_cf_config = ibm_cf_config
        self.package = 'pywren_v'+__version__
        self.cf_client = CloudFunctionsClient(self.ibm_cf_config)
        self.is_cf_cluster = is_cf_cluster()

        self.region = ibm_cf_config['endpoint'].split('//')[1].split('.')[0]
        self.namespace = ibm_cf_config['namespace']
        log_msg = 'PyWren v{} init for IBM Cloud Functions - Namespace: {} - Region: {}'.format(__version__, self.namespace, self.region)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)

    def _format_action_name(self, runtime_name, runtime_memory):
        runtime_name = runtime_name.replace('/', '_').replace(':', '_')
        return '{}_{}MB'.format(runtime_name, runtime_memory)

    def _unformat_action_name(self, action_name):
        runtime_name, memory = action_name.rsplit('_', 1)
        image_name = runtime_name.replace('_', '/', 1)
        image_name = image_name.replace('_', ':', -1)
        return image_name, int(memory.replace('MB', ''))

    def create_runtime(self, docker_image_name, memory, code=None, is_binary=True, timeout=300000):
        self.cf_client.create_package(self.package)
        action_name = self._format_action_name(docker_image_name, memory)
        self.cf_client.create_action(self.package, action_name, docker_image_name, code=code,
                                     memory=memory, is_binary=is_binary, timeout=timeout)
        return action_name

    def delete_runtime(self, docker_image_name, memory):
        action_name = self._format_action_name(docker_image_name, memory)
        self.cf_client.delete_action(self.package, action_name)

    def delete_all_runtimes(self):
        packages = self.cf_client.list_packages()
        for pkg in packages:
            if 'pywren_v' in pkg['name']:
                actions = self.cf_client.list_actions(pkg['name'])
                while actions:
                    for action in actions:
                        self.cf_client.delete_action(pkg['name'], action['name'])
                    actions = self.cf_client.list_actions(pkg['name'])
                self.cf_client.delete_package(pkg['name'])

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes deployed in the IBM CF service
        return: list of tuples [docker_image_name, memory]
        """
        runtimes = []
        actions = self.cf_client.list_actions(self.package)

        for action in actions:
            action_image_name, memory = self._unformat_action_name(action['name'])
            if docker_image_name == action_image_name or docker_image_name == 'all':
                runtimes.append([action_image_name, memory])
        return runtimes

    def invoke(self, runtime_name, runtime_memory, payload):
        """
        Invoke -- return information about this invocation
        """
        action_name = self._format_action_name(runtime_name, runtime_memory)
        return self.cf_client.invoke(self.package, action_name, payload, self.is_cf_cluster)

    def invoke_with_result(self, runtime_name, runtime_memory, payload={}):
        """
        Invoke waiting for a result -- return information about this invocation
        """
        action_name = self._format_action_name(runtime_name, runtime_memory)
        return self.cf_client.invoke_with_result(self.package, action_name, payload)

    def get_runtime_key(self, runtime_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        action_name = self._format_action_name(runtime_name, runtime_memory)
        runtime_key = os.path.join(self.name, self.region, self.namespace, action_name)

        return runtime_key

    def create_handler_zip(self, module_location, zip_location):
        logger.debug("Creating function handler zip in {}".format(zip_location))

        def add_folder_to_zip(zip_file, full_dir_path, sub_dir=''):
            for file in os.listdir(full_dir_path):
                full_path = os.path.join(full_dir_path, file)
                if os.path.isfile(full_path):
                    zip_file.write(full_path, os.path.join('pywren_ibm_cloud', sub_dir, file), zipfile.ZIP_DEFLATED)
                elif os.path.isdir(full_path) and '__pycache__' not in full_path:
                    add_folder_to_zip(zip_file, full_path, os.path.join(sub_dir, file))

        try:
            with zipfile.ZipFile(zip_location, 'w') as ibmcf_pywren_zip:
                my_location = os.path.dirname(os.path.abspath(__file__))
                main_file = os.path.join(my_location, 'entry_point.py')
                ibmcf_pywren_zip.write(main_file, '__main__.py', zipfile.ZIP_DEFLATED)
                add_folder_to_zip(ibmcf_pywren_zip, module_location)
        except Exception:
            raise Exception('Unable to create the {} action package'.format(zip_location))
