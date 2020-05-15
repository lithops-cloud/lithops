import os
import json
import sys
import time
import zipfile
import requests
import logging
import tempfile
import subprocess
import multiprocessing
import pywren_ibm_cloud
from shutil import copyfile
from . import config as docker_config
from pywren_ibm_cloud.utils import version_str
from pywren_ibm_cloud.config import JOBS_PREFIX
from pywren_ibm_cloud.version import __version__

logger = logging.getLogger(__name__)

TEMP = tempfile.gettempdir()
STORAGE_BASE_DIR = os.path.join(TEMP, JOBS_PREFIX)
LOCAL_RUN_DIR = os.path.join(os.getcwd(), 'pywren_jobs')

logging.getLogger('urllib3.connectionpool').setLevel(logging.CRITICAL)


class DockerBackend:
    """
    A wrap-up around Docker APIs.
    """

    def __init__(self, docker_config):
        self.log_level = os.getenv('PYWREN_LOGLEVEL')
        self.config = docker_config
        self.name = 'docker'
        self.run_dir = LOCAL_RUN_DIR
        self.host = docker_config['host']
        self.queue = multiprocessing.Queue()
        self._is_localhost = self.host in ['127.0.0.1', 'localhost']

        log_msg = 'PyWren v{} init for Docker - Host: {}'.format(__version__, self.host)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)

    def _format_runtime_name(self, docker_image_name):
        name = docker_image_name.replace('/', '_').replace(':', '_')
        return 'pywren_{}'.format(name)

    def _unformat_runtime_name(self, runtime_name):
        image_name = runtime_name.replace('pywren_', '')
        image_name = image_name.replace('_', '/', 1)
        image_name = image_name.replace('_', ':', -1)
        return image_name, None

    def _get_default_runtime_image_name(self):
        python_version = version_str(sys.version_info)
        return docker_config.RUNTIME_DEFAULT[python_version]

    def _create_function_handler_zip(self):
        logger.debug("Creating function handler zip in {}".format(docker_config.FH_ZIP_LOCATION))

        def add_folder_to_zip(zip_file, full_dir_path, sub_dir=''):
            for file in os.listdir(full_dir_path):
                full_path = os.path.join(full_dir_path, file)
                if os.path.isfile(full_path):
                    zip_file.write(full_path, os.path.join('pywren_ibm_cloud', sub_dir, file))
                elif os.path.isdir(full_path) and '__pycache__' not in full_path:
                    add_folder_to_zip(zip_file, full_path, os.path.join(sub_dir, file))

        try:
            with zipfile.ZipFile(docker_config.FH_ZIP_LOCATION, 'w', zipfile.ZIP_DEFLATED) as docker_pywren_zip:
                current_location = os.path.dirname(os.path.abspath(__file__))
                module_location = os.path.dirname(os.path.abspath(pywren_ibm_cloud.__file__))
                main_file = os.path.join(current_location, 'entry_point.py')
                docker_pywren_zip.write(main_file, '__main__.py')
                add_folder_to_zip(docker_pywren_zip, module_location)
        except Exception as e:
            raise Exception('Unable to create the {} package: {}'.format(docker_config.FH_ZIP_LOCATION, e))

    def _delete_function_handler_zip(self):
        os.remove(docker_config.FH_ZIP_LOCATION)

    def _init_runtime(self, docker_image_name):
        name = self._format_runtime_name(docker_image_name)
        running_runtimes_cmd = "docker ps --format '{{.Names}}' -f name=pywren"
        uid_cmd = "id -u $USER"

        if self._is_localhost:
            uid = subprocess.check_output(uid_cmd, shell=True).decode().strip()
            running_runtimes = subprocess.run(running_runtimes_cmd, shell=True, stdout=subprocess.PIPE).stdout.decode()
            if name not in running_runtimes:
                cmd = ('docker run -d --name pywren_{} --user {} -v /tmp:/tmp -p 8080:8080'
                       ' --entrypoint "python" {} /tmp/pywren.docker/__main__.py >/dev/null 2>&1'
                       .format(name, uid, docker_image_name))
                res = os.system(cmd)
                if res != 0:
                    raise Exception('There was an error starting the runtime')
                time.sleep(5)
        else:
            pass

    def _generate_runtime_meta(self, docker_image_name):
        """
        Extracts installed Python modules from the local machine
        """
        self._init_runtime(docker_image_name)

        r = requests.get('http://{}:{}/preinstalls'.format(self.host, docker_config.PYWREN_SERVER_PORT))
        runtime_meta = r.json()

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        return runtime_meta

    def invoke(self, docker_image_name, memory, payload):
        """
        Invoke the function with the payload. runtime_name and memory
        are not used since it runs in the local machine.
        """
        self._init_runtime(docker_image_name)
        r = requests.post("http://{}:{}/".format(self.host, docker_config.PYWREN_SERVER_PORT), data=json.dumps(payload))
        response = r.json()
        return response['activationId']

    def create_runtime(self, docker_image_name, memory, timeout):
        """
        Pulls the docker image from the docker hub and copies
        the necessary files to the host.
        """
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()

        self._create_function_handler_zip()

        if self._is_localhost:
            df_path = os.path.join(TEMP, 'pywren.docker')
            os.makedirs(df_path, exist_ok=True)

            archive = zipfile.ZipFile(docker_config.FH_ZIP_LOCATION)
            for file in archive.namelist():
                archive.extract(file, df_path)

            cmd = 'docker pull {} >/dev/null 2>&1'.format(docker_image_name)
            res = os.system(cmd)
            if res != 0:
                raise Exception('There was an error pulling the runtime')
        else:
            pass

        self._delete_function_handler_zip()
        runtime_meta = self._generate_runtime_meta(docker_image_name)

        return runtime_meta

    def build_runtime(self, docker_image_name, dockerfile):
        """
        Builds a new runtime from a Dockerfile
        """
        raise Exception('You must use an IBM CF/knative built runtime')

    def delete_runtime(self, docker_image_name, memory):
        """
        Deletes a runtime
        """
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()

        logger.debug('Deleting {} runtime'.format(docker_image_name))
        if self._is_localhost:
            name = self._format_runtime_name(docker_image_name)
            cmd = 'docker rm -f {} >/dev/null 2>&1'.format(name)
            os.system(cmd)
            #cmd = 'docker rmi -f {} >/dev/null 2>&1'.format(docker_image_name)
            #os.system(cmd)

    def delete_all_runtimes(self):
        """
        Delete all created runtimes
        """
        list_runtimes_cmd = "docker ps -a -f name=pywren | awk '{print $NF}' | tail -n +2"
        if self._is_localhost:
            runtimes = subprocess.check_output(list_runtimes_cmd, shell=True).decode().strip()
            for runtime in runtimes.splitlines():
                logger.debug('Deleting {} runtime'.format(runtime))
                cmd = 'docker rm -f {} >/dev/null 2>&1'.format(runtime)
                os.system(cmd)
        else:
            pass

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes deployed in the local machine
        return: list of tuples (docker_image_name, memory)
        """
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()
        runtimes = []
        list_runtimes_cmd = "docker ps -a -f name=pywren | awk '{print $NF}' | tail -n +2"
        if self._is_localhost:
            runtimes = subprocess.check_output(list_runtimes_cmd, shell=True).decode().strip()
        else:
            pass

        for runtime in runtimes.splitlines():
            name = self._format_runtime_name(docker_image_name)
            if name == runtime or docker_image_name == 'all':
                tag = self._unformat_runtime_name(runtime)
                runtimes.append((tag, None))

        return runtimes

    def get_runtime_key(self, docker_image_name, memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know what runtimes are installed and what not.
        """
        runtime_name = self._format_runtime_name(docker_image_name)
        runtime_key = os.path.join(self.name, self.host, runtime_name)

        return runtime_key
