import os
import sys
import logging
import shutil
import json
import lithops
import oci

from lithops import utils
from lithops.version import __version__
from lithops.constants import COMPUTE_CLI_MSG, TEMP_DIR

from . import config

logger = logging.getLogger(__name__)


class OracleCloudFunctionsBackend:

    def __init__(self, oracle_config, storage_config):
        self.name = 'oracle_f'
        self.type = 'faas'
        self.config = oracle_config
        self.region = oracle_config['region']
        self.tenancy = oracle_config['tenancy']
        self.compartment_id = oracle_config['compartment_id']
        self.user = oracle_config['user']
        self.namespace_name = oracle_config['namespace_name']
        self.username = oracle_config['username']
        self.auth_token = oracle_config['auth_token']
        
        self.default_service_name = f'{config.SERVICE_NAME}_{self.user[-5:-1].lower()}'
        self.service_name = oracle_config.get('service', self.default_service_name)
        
        self.cf_client = oci.functions.FunctionsManagementClient(oracle_config)
    
    def _format_function_name(self, runtime_name, runtime_memory, version=__version__):
        runtime_name = ('lithops_v' + version + '_' + runtime_name).replace('.', '-')
        return f'{runtime_name}_{runtime_memory}MB'
    
    def _unformat_function_name(self, function_name):
        runtime_name, runtime_memory = function_name.rsplit('_', 1)
        runtime_name = runtime_name.replace('lithops_v', '')
        version, runtime_name = runtime_name.split('_', 1)
        version = version.replace('-', '.')
        return version, runtime_name, runtime_memory.replace('MB', '')
    def get_runtime_key(self, runtime_name, runtime_memory, version=__version__):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        function_name = self._format_function_name(runtime_name, runtime_memory, version)
        runtime_key = os.path.join(self.name, version, self.region, self.service_name, function_name)

        return runtime_key

    def _get_default_runtime_name(self):
        py_version = utils.CURRENT_PY_VERSION.replace('.', '')
        return f'lithops-default-runtime-v{py_version}'
    
    def _build_default_runtime(self, runtime_name):
        """
        Builds the default runtime
        """
        requirements_file = os.path.join(TEMP_DIR, 'oracle_default_requirements.txt')
        with open(requirements_file, 'w') as reqf:
            reqf.write(config.REQUIREMENTS_FILE)
        try:
            self.build_runtime(runtime_name, requirements_file)
        finally:
            os.remove(requirements_file)
    
    def build_runtime(self, docker_image_name, dockerfile, extra_args=[]):
        logger.info(f'Building runtime {docker_image_name} from {dockerfile}')
        print('Building runtime {docker_image_name} from {dockerfile}')
        docker_path = utils.get_docker_path()

        cmd = f'{docker_path} login {self.region}.ocir.io -u {self.namespace_name}/{self.username} -p {self.auth_token}'
        utils.run_command(cmd)
        print(dockerfile)
        # Build the Docker image

        if dockerfile:
            assert os.path.isfile(dockerfile), f'Cannot locate "{dockerfile}"'
            cmd = f'{docker_path} build -t {docker_image_name} -f {dockerfile} . '
        else:
            cmd = f'{docker_path} build -t {docker_image_name} . '
        utils.run_command(cmd)
        
        # Tag the image with the appropriate name and version
        #utils.run_command(f'{docker_path} "tag" {runtime_name} {self.region}.ocir.io/{self.namespace_name}/{runtime_name}')

      

    


    def get_runtime_info(self):
        """
        Method that returns all the relevant information about the runtime set
        in config
        """
        if utils.CURRENT_PY_VERSION not in config.AVAILABLE_PY_RUNTIMES:
            raise Exception(
                f'Python {utils.CURRENT_PY_VERSION} is not available for Oracle '
                f'Functions. Please use one of {list(config.AVAILABLE_PY_RUNTIMES.keys())}'
            )

        if 'runtime' not in self.config or self.config['runtime'] == 'default':
            self.config['runtime'] = self._get_default_runtime_name()

        runtime_info = {
            'runtime_name': self.config['runtime'],
            'runtime_memory': self.config['runtime_memory'],
            'runtime_timeout': self.config['runtime_timeout'],
            'max_workers': self.config['max_workers'],
        }

        return runtime_info
    def _service_exists(self, service_name):
        """
        Checks if a given service exists
        """
        services = self.cf_client.list_applications(self.config['tenancy']).data
        for serv in services:
            if serv.display_name == service_name:
                
                return True
        return False

    def _get_application_id(self, service_name):
        """
        Returns the application id of a given application
        """
        services = self.cf_client.list_applications(self.config['tenancy']).data
        for serv in services:
            if serv.display_name == service_name:
                return serv.id
        return None

    def deploy_runtime(self, runtime_name, memory, timeout):
            """
            Deploys a new runtime into Aliyun Function Compute
            with the custom modules for lithops
            """
            logger.info(f"Deploying runtime: {runtime_name} - Memory: {memory} Timeout: {timeout}")

            if not self._service_exists(self.service_name):
                logger.debug(f"creating service {self.service_name}")
                
                self.cf_client.create_application(
                create_application_details=oci.functions.models.CreateApplicationDetails(
                compartment_id=self.tenancy,
                display_name=self.service_name,
                subnet_ids=[self.config['subnet_ids']]))

            
            if runtime_name == self._get_default_runtime_name():
                self._build_default_runtime(runtime_name)

            function_name = self._format_function_name(runtime_name, memory)
            app_id = self._get_application_id(self.service_name)

            print(app_id)
            logger.debug(f'Creating function {function_name}')
            functions = self.cf_client.list_functions(app_id).data
            
            for function in functions:
                if function['functionName'] == function_name:
                    logger.debug(f'Function {function_name} already exists. Deleting it')
                    self.delete_runtime(runtime_name, memory)

            self.cf_client.create_function(
                create_function_details=oci.functions.models.CreateFunctionDetails(
                display_name=function_name,
                application_id=app_id,
                image="EXAMPLE-image-Value",
                memory_in_mbs=memory))

            metadata = self._generate_runtime_meta(function_name)

            return metadata

       
"""
if __name__ == "__main__":
    config1 = {
        
        "user": "ocid1.user.oc1..aaaaaaaa35yjlnfrox4km4cmwectgtclrgwvpmjrheuyqi3tj3biavqxkmiq",
        "key_file": "/home/ayman/ayman.bourramouss@urv.cat_2023-01-09T12_07_06.729Z.pem",
        "fingerprint": "cf:b9:a6:85:a5:6e:06:23:20:35:76:af:71:ff:a9:52",
        "tenancy": "ocid1.tenancy.oc1..aaaaaaaaedomxxeig7qoo5fmbbvsohbmp6nial74sh2so32zk3wxnc2erxta",
        "region": "eu-madrid-1",
        "compartment_id": "ocid1.compartment.oc1..aaaaaaaa6fwt7css3rvvryfi5gjrqvrdakkdlkizltk7c7dxy35bfkpms57q",
        "namespace_name":"axwup7ph7ej7"
    }
    
    f = OracleCloudFunctionsBackend(config1).cf_client

    print(f.get_application('ocid1.fnapp.oc1.eu-madrid-1.aaaaaaaauxuxuzklmzikfbwzjmtb5m2qqal4azoebsoycv33isu22xewsvra').data)

"""     
