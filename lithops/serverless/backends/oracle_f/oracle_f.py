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

LITHOPS_FUNCTION_ZIP = 'lithops_oracle.zip'

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
       
        return runtime_name
    
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
    @staticmethod
    def _create_handler_bin(remove=True):
        """
        Create and return Lithops handler function as zip bytes
        @param remove: True to delete the zip archive after building
        @return: Lithops handler function as zip bytes
        """
        current_location = os.path.dirname(os.path.abspath(__file__))
        main_file = os.path.join(current_location, 'entry_point.py')
        utils.create_handler_zip(LITHOPS_FUNCTION_ZIP, main_file, 'entry_point.py')

        with open(LITHOPS_FUNCTION_ZIP, 'rb') as action_zip:
            action_bin = action_zip.read()

        if remove:
            os.remove(LITHOPS_FUNCTION_ZIP)

        return action_bin

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
        
        dockerfile_content = f'''
            FROM python:{utils.CURRENT_PY_VERSION}-slim

            WORKDIR /app

            COPY {os.path.basename(requirements_file)} ./
            RUN pip install --no-cache-dir -r {os.path.basename(requirements_file)}

            CMD ["python", "-c", "print('Hello from the Oracle Functions runtime!')"]
        '''
        dockerfile_path = os.path.join(TEMP_DIR, 'oracle_default_Dockerfile')
        shutil.copy(requirements_file, './oracle_default_requirements.txt')

        with open(dockerfile_path, 'w') as dockerfile:
            dockerfile.write(dockerfile_content)

        try:
            self.build_runtime(runtime_name, dockerfile_path)
        finally:
            print('Cleaning up')
    
    def build_runtime(self, docker_image_name, dockerfile, extra_args=[]):
        """ Build the runtime Docker image and push it to OCIR. """
        
        logger.info(f'Building runtime {docker_image_name} from {dockerfile}')
        print('Building runtime {docker_image_name} from {dockerfile}')
        docker_path = utils.get_docker_path()

        cmd = f'{docker_path} login {self.region}.ocir.io -u {self.namespace_name}/{self.username} --password-stdin'
        
        out = utils.run_command(cmd, return_result=True, input=self.auth_token)
        print(out)
        
        # Create Lithops handler zip file
        try:
            self._create_handler_bin(remove=False)
            
            # Build the Docker image
            if dockerfile:
                assert os.path.isfile(dockerfile), f'Cannot locate "{dockerfile}"'
                cmd = f'{docker_path} build -t {docker_image_name} -f {dockerfile} . '
            else:
                cmd = f'{docker_path} build -t {docker_image_name} . '

            output = utils.run_command(cmd, return_result=True)
            print(output)
        finally:
            os.remove(LITHOPS_FUNCTION_ZIP)

        cmd = f'{docker_path} tag {docker_image_name}:latest {self.region}.ocir.io/{self.namespace_name}/{docker_image_name}:latest'
        utils.run_command(cmd)
        
        # Push the Docker image to the Oracle Cloud Infrastructure Registry (OCIR)
        cmd = f'{docker_path} push {self.region}.ocir.io/{self.namespace_name}/{docker_image_name}:latest'
        utils.run_command(cmd)


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
        Deploys a new runtime into Oracle Function Compute
        with the custom modules for lithops
        """
        logger.info(f"Deploying runtime: {runtime_name} - Memory: {memory} Timeout: {timeout}")

        if not self._service_exists(self.service_name):
            logger.debug(f"Creating service {self.service_name}")
            self.cf_client.create_application(
                create_application_details=oci.functions.models.CreateApplicationDetails(
                    compartment_id=self.tenancy,
                    display_name=self.service_name,
                    subnet_ids=[self.config['subnet_ids']]))

        function_name = self._format_function_name(runtime_name, memory)
        app_id = self._get_application_id(self.service_name)

        logger.debug(f'Checking if function {function_name} exists')
        functions = self.cf_client.list_functions(app_id).data

        existing_function = None
        for function in functions:
            if function.display_name == function_name:
                existing_function = function
                break

        docker_image_name = f'{self.region}.ocir.io/{self.namespace_name}/{runtime_name}:latest'

        if existing_function:
            logger.debug(f'Function {function_name} already exists. Updating it')
            self.cf_client.update_function(
                function_id=existing_function.id,
                update_function_details=oci.functions.models.UpdateFunctionDetails(
                    image=docker_image_name,
                    memory_in_mbs=memory,
                    timeout_in_seconds=timeout))
        else:
            logger.debug(f'Creating function {function_name}')
            self.cf_client.create_function(
                create_function_details=oci.functions.models.CreateFunctionDetails(
                    display_name=function_name,
                    application_id=app_id,
                    image=docker_image_name,
                    memory_in_mbs=memory,
                    timeout_in_seconds=timeout))

        print("before generate_runtime_metadata")
        metadata = self._generate_runtime_meta(function_name)

        return metadata

    def _generate_runtime_meta(self, runtime_name):
        logger.debug(f'Extracting runtime metadata from: {runtime_name}')

        # Get the function ID
        app_id = self._get_application_id(self.service_name)
        function_name = self._format_function_name(runtime_name, self.config['runtime_memory'])
        function_ocid = self._get_function_ocid(function_name, app_id)

        # Retrieve the function's information, including the invoke endpoint
        fn_info = self.cf_client.get_function(function_ocid).data

        # Set the invoke endpoint
        invoke_endpoint = fn_info.invoke_endpoint

        # Prepare the Oracle Functions client with the invoke endpoint
        fn_invoke_client = oci.functions.FunctionsInvokeClient(self.config, service_endpoint=invoke_endpoint)

        # Prepare the payload with the 'get_metadata' argument
        payload = json.dumps({"get_metadata": True}).encode()

        # Invoke the function with the payload
        response = fn_invoke_client.invoke_function(
            function_id=function_ocid,
            invoke_function_body=payload
        )

        print(response.data.text())
        result = json.loads(response.data.text())

        if 'lithops_version' in result:
            return result
        else:
            raise Exception('An error occurred: {}'.format(result))


    def _get_function_ocid(self, runtime_name, app_id):
       

        if app_id is None:
            raise Exception(f'Application {runtime_name} not found.')

        # Get the list of functions within the found application
        functions = self.cf_client.list_functions(app_id).data

        # Search for the function and return its OCID
        for function in functions:
            if function.display_name == runtime_name:
                return function.id

        raise Exception(f'Function {runtime_name} not found.')

