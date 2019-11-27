import os
import json
import sys
import uuid
import docker
import logging
import tempfile
import multiprocessing
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
        self.queue = multiprocessing.Queue()
        self.workers = self.config['workers']
        self.docker_client = docker.from_env()

        for cpu in range(self.workers):
            p = multiprocessing.Process(target=self._process_runner)
            p.daemon = True
            p.start()

        log_msg = 'PyWren v{} init for Docker - Total workers: {}'.format(__version__, self.workers)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)

    def _process_runner(self):
        while True:
            docker_image_name, payload = self.queue.get(block=True)
            exec_id = payload['executor_id']
            job_id = payload['job_id']
            call_id = payload['call_id']

            payload_dir = os.path.join(STORAGE_BASE_DIR, exec_id, job_id, call_id)
            os.makedirs(payload_dir, exist_ok=True)
            payload_filename = os.path.join(payload_dir, 'payload.json')

            with open(payload_filename, "w") as f:
                f.write(json.dumps(payload))

            self.docker_client.containers.run(docker_image_name, ['run', payload_filename],
                                              volumes=['{}:/tmp'.format(TEMP)],
                                              detach=False, auto_remove=True)

    def _format_runtime_name(self, docker_image_name, runtime_memory):
        runtime_name = docker_image_name.replace('/', '_').replace(':', '_')
        return '{}_{}MB'.format(runtime_name, runtime_memory)

    def _unformat_runtime_name(self, action_name):
        runtime_name, memory = action_name.rsplit('_', 1)
        image_name = runtime_name.replace('_', '/', 1)
        image_name = image_name.replace('_', ':', -1)
        return image_name, int(memory.replace('MB', ''))

    def _get_default_runtime_image_name(self):
        this_version_str = version_str(sys.version_info)
        if this_version_str == '3.5':
            image_name = docker_config.RUNTIME_DEFAULT_35
        elif this_version_str == '3.6':
            image_name = docker_config.RUNTIME_DEFAULT_36
        elif this_version_str == '3.7':
            image_name = docker_config.RUNTIME_DEFAULT_37
        return image_name

    def _get_default_dockefile(self):
        this_version_str = version_str(sys.version_info)
        if this_version_str == '3.5':
            dockefile = docker_config.DOCKERFILE_DEFAULT_35
        elif this_version_str == '3.6':
            dockefile = docker_config.DOCKERFILE_DEFAULT_36
        elif this_version_str == '3.7':
            dockefile = docker_config.DOCKERFILE_DEFAULT_37
        return dockefile

    def _generate_runtime_meta(self, docker_image_name):
        """
        Extracts installed Python modules from the local machine
        """
        runtime_meta = self.docker_client.containers.run(docker_image_name,
                                                         'metadata',
                                                         auto_remove=True)
        runtime_meta = json.loads(runtime_meta)

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        return runtime_meta

    def invoke(self, docker_image_name, memory, payload):
        """
        Invoke the function with the payload. runtime_name and memory
        are not used since it runs in the local machine.
        """
        self.queue.put((docker_image_name, payload))
        act_id = str(uuid.uuid4()).replace('-', '')[:12]
        return act_id

    def create_runtime(self, docker_image_name, memory, timeout):
        """
        Extracts local python metadata. No need to create any runtime
        since it runs in the local machine
        """
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()

        runtime = self.list_runtimes(docker_image_name)
        if not runtime:
            logger.debug("Default image is not yet created")
            current_location = os.path.dirname(os.path.abspath(__file__))
            df_path = os.path.join(TEMP, 'pywren.docker')
            os.makedirs(df_path, exist_ok=True)
            copyfile(os.path.join(current_location, 'entry_point.py'),
                     os.path.join(df_path, 'entry_point.py'))
            with open(os.path.join(df_path, 'Dockerfile'), "w") as f:
                dockerfile = self._get_default_dockefile()
                f.write(dockerfile)
            self._build_runtime(docker_image_name, df_path)

        runtime_meta = self._generate_runtime_meta(docker_image_name)

        return runtime_meta

    def _build_runtime(self, docker_image_name, dockerfile_path):
        """
        Builds a new runtime from a Dockerfile path
        """
        logger.debug('Building a new docker image from Dockerfile')
        logger.debug('Dockefile path: {}'.format(dockerfile_path))
        logger.debug('Docker image name: {}'.format(docker_image_name))

        self.docker_client.images.build(path=dockerfile_path, tag=docker_image_name)

    def build_runtime(self, docker_image_name, dockerfile):
        """
        Builds a new runtime from a Dockerfile
        """
        logger.info('Building a new docker image from Dockerfile')
        logger.info('Docker image name: {}'.format(docker_image_name))

        if dockerfile:
            cmd = 'docker build -t {} -f {} .'.format(docker_image_name, dockerfile)
        else:
            cmd = 'docker build -t {} .'.format(docker_image_name)

        res = os.system(cmd)
        if res != 0:
            exit()

    def delete_runtime(self, docker_image_name, memory):
        """
        Deletes a runtime
        """
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()
        self.docker_client.images.remove(docker_image_name, force=True)

    def delete_all_runtimes(self):
        """
        Delete all Default runtimes
        """
        try:
            self.docker_client.images.remove(docker_config.RUNTIME_DEFAULT_35, force=True)
        except Exception:
            pass
        try:
            self.docker_client.images.remove(docker_config.RUNTIME_DEFAULT_36, force=True)
        except Exception:
            pass
        try:
            self.docker_client.images.remove(docker_config.RUNTIME_DEFAULT_37, force=True)
        except Exception:
            pass

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes deployed in the local machine
        return: list of tuples (docker_image_name, memory)
        """
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()
        runtimes = []
        images = self.docker_client.images.list()
        for img in images:
            for tag in img.tags:
                if docker_image_name in tag or docker_image_name == 'all':
                    runtimes.append((tag, None))

        return runtimes

    def get_runtime_key(self, docker_image_name, memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know what runtimes are installed and what not.
        """
        runtime_name = self._format_runtime_name(docker_image_name, memory)
        runtime_key = os.path.join(self.name, runtime_name)

        return runtime_key
