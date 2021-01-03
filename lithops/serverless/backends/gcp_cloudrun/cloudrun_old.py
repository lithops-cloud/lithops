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
import re
import sys
import ssl
import json
import shutil
import urllib3
import logging
import requests
import subprocess
import http.client
from urllib.parse import urlparse
from lithops.utils import version_str
from lithops.version import __version__
from lithops.utils import create_handler_zip
from lithops.constants import COMPUTE_CLI_MSG
from . import config as cr_config

urllib3.disable_warnings()


logger = logging.getLogger(__name__)


class CloudRunServingBackend:
    """
    A wrap-up around Cloud Run Serving APIs.
    """

    def __init__(self, cloudrun_config, storage_config):
        logger.debug("Creating Google Cloud Run client")
        self.name = 'cloudrun'
        self.cloudrun_config = cloudrun_config
        self.region = self.cloudrun_config.get('region')
        self.namespace = self.cloudrun_config.get('namespace', 'default')
        self.cluster = self.cloudrun_config.get('cluster', 'default')
        self.workers = self.cloudrun_config.get('workers')

        msg = COMPUTE_CLI_MSG.format('Google Cloud Run')
        logger.info("{} - Region: {} - Namespace: {}".format(msg, self.region, self.namespace))

    def _format_service_name(self, runtime_name, runtime_memory):
        runtime_name = runtime_name.replace('/', '--').replace(':', '--')
        return '{}--{}mb'.format(runtime_name, runtime_memory)

    def _unformat_service_name(self, service_name):
        runtime_name, memory = service_name.rsplit('--', 1)
        image_name = runtime_name.replace('--', '/', 1)
        image_name = image_name.replace('--', ':', -1)
        return image_name, int(memory.replace('mb', ''))

    def _get_default_runtime_image_name(self):
        project_id = self.cloudrun_config['project_id']
        python_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'dev' in __version__ else __version__.replace('.', '')
        return '{}/{}-v{}:{}'.format(project_id, cr_config.RUNTIME_NAME_DEFAULT, python_version, revision)

    def _get_service_host(self, service_name):
        """
        gets the service host needed for the invocation
        """
        logger.debug('Getting service host for: {}'.format(service_name))

        cmd = 'gcloud run services describe {} --platform=managed --region={} --format=json'.format(service_name, self.region)
        out = subprocess.check_output(cmd, shell=True).decode("ascii")
        service_host = json.loads(out)["status"]["url"][8:]

        logger.debug('Service host: {}'.format(service_host))
        return service_host

    def _build_default_runtime(self, default_runtime_img_name):
        """
        Builds the default runtime
        """
        location = 'https://raw.githubusercontent.com/tomwhite/lithops/master/runtime/cloudrun'
        python_version = version_str(sys.version_info).replace('.', '')
        resp = requests.get('{}/Dockerfile.python{}'.format(location, python_version))
        dockerfile = "Dockerfile"
        if resp.status_code == 200:
            with open(dockerfile, 'w') as f:
                f.write(resp.text)
            self.build_runtime(default_runtime_img_name, dockerfile)
            os.remove(dockerfile)
        else:
            msg = 'There was an error fetching the default runtime Dockerfile: {}'.format(resp.text)
            logger.error(msg)
            exit()

    def _create_service(self, docker_image_name, runtime_memory, timeout):

        service_name = self._format_service_name(docker_image_name, runtime_memory)

        cmd = 'gcloud run deploy --allow-unauthenticated --platform=managed --region={} --image gcr.io/{} --max-instances={} --memory={} --timeout={} --concurrency=1 {}'.format(
            self.region, docker_image_name, self.workers, '{}Mi'.format(runtime_memory), timeout, service_name
        )

        if logger.getEffectiveLevel() != logging.DEBUG:
            cmd = cmd + " >{} 2>&1".format(os.devnull)

        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error creating the service')

    def _generate_runtime_meta(self, docker_image_name, memory):
        """
        Extract installed Python modules from docker image
        """
        payload = {}

        payload['service_route'] = "/preinstalls"
        logger.debug("Extracting Python modules list from: {}".format(docker_image_name))
        try:
            runtime_meta = self.invoke(docker_image_name, memory, payload, return_result=True)
        except Exception as e:
            raise Exception("Unable to invoke 'modules' action: {}".format(e))

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception('Failed getting runtime metadata: {}'.format(runtime_meta))

        return runtime_meta

    def create_runtime(self, docker_image_name, memory, timeout=cr_config.RUNTIME_TIMEOUT_DEFAULT):

        default_runtime_img_name = self._get_default_runtime_image_name()
        if docker_image_name in ['default', default_runtime_img_name]:
            docker_image_name = default_runtime_img_name
            self._build_default_runtime(default_runtime_img_name)

        self._create_service(docker_image_name, memory, timeout)
        runtime_meta = self._generate_runtime_meta(docker_image_name, memory)

        return runtime_meta

    def _delete_function_handler_zip(self):
        os.remove(cr_config.FH_ZIP_LOCATION)

    def build_runtime(self, docker_image_name, dockerfile):
        """
        Builds a new runtime from a Docker file and pushes it to the Docker hub
        """
        logger.info('Building a new docker image from Dockerfile')
        logger.info('Docker image name: {}'.format(docker_image_name))

        # Project ID can contain '-'
        expression = '^([-a-z0-9]+)/([-a-z0-9]+)(:[a-z0-9]+)?'
        result = re.match(expression, docker_image_name)

        if not result or result.group() != docker_image_name:
            raise Exception("Invalid docker image name: '.' or '_' characters are not allowed")

        entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
        create_handler_zip(cr_config.FH_ZIP_LOCATION, entry_point, 'lithopsproxy.py')

        # Dockerfile has to be called "Dockerfile" (and in cwd) for 'gcloud builds submit' to work
        if dockerfile != "Dockerfile":
            shutil.copyfile(dockerfile, "Dockerfile")
        cmd = 'gcloud builds submit -t gcr.io/{}'.format(docker_image_name)

        if logger.getEffectiveLevel() != logging.DEBUG:
            cmd = cmd + " >{} 2>&1".format(os.devnull)

        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error building the runtime')

        self._delete_function_handler_zip()

    def delete_runtime(self, docker_image_name, memory):
        service_name = self._format_service_name(docker_image_name, memory)
        logger.info('Deleting runtime: {}'.format(service_name))

        cmd = 'gcloud run services delete {} --platform=managed --region={} --quiet'.format(service_name, self.region)

        if logger.getEffectiveLevel() != logging.DEBUG:
            cmd = cmd + " >{} 2>&1".format(os.devnull)

        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error deleting the runtime')

    def clean(self):
        """
        Deletes all runtimes deployed
        """
        runtimes = self.list_runtimes()
        for docker_image_name, memory in runtimes:
            self.delete_runtime(docker_image_name, memory)

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes deployed
        return: list of tuples [docker_image_name, memory]
        """
        runtimes = []

        cmd = 'gcloud run services list --platform=managed --region={} --format=json'.format(self.region)
        out = subprocess.check_output(cmd, shell=True).decode("ascii")
        json_out = json.loads(out)
        for service in json_out:
            runtime_name = service['metadata']['name']
            if '--' not in runtime_name:
                continue
            image_name, memory = self._unformat_service_name(runtime_name)
            if docker_image_name == image_name or docker_image_name == 'all':
                runtimes.append((image_name, memory))

        return runtimes

    def invoke(self, docker_image_name, memory, payload, return_result=False):
        """
        Invoke -- return information about this invocation
        """
        service_name = self._format_service_name(docker_image_name, memory)
        service_host = self._get_service_host(service_name)

        headers = {}

        endpoint = 'https://{}'.format(service_host)

        exec_id = payload.get('executor_id')
        call_id = payload.get('call_id')
        job_id = payload.get('job_id')
        route = payload.get("service_route", '/')

        try:
            parsed_url = urlparse(endpoint)

            if endpoint.startswith('https'):
                ctx = ssl._create_unverified_context()
                conn = http.client.HTTPSConnection(parsed_url.netloc, context=ctx)
            else:
                conn = http.client.HTTPConnection(parsed_url.netloc)

            conn.request("POST", route, body=json.dumps(payload), headers=headers)

            if exec_id and job_id and call_id:
                logger.debug('ExecutorID {} | JobID {} - Function call {} invoked'
                             .format(exec_id, job_id, call_id))
            elif exec_id and job_id:
                logger.debug('ExecutorID {} | JobID {} - Function invoked'
                             .format(exec_id, job_id))
            else:
                logger.debug('Function invoked')

            resp = conn.getresponse()
            resp_status = resp.status
            resp_data = resp.read().decode("utf-8")
            conn.close()
        except Exception as e:
            raise e

        if resp_status in [200, 202]:
            data = json.loads(resp_data)
            if return_result:
                return data
            return data["activationId"]
        elif resp_status == 404:
            raise Exception("Lithops runtime is not deployed in your k8s cluster")
        else:
            logger.debug('ExecutorID {} | JobID {} - Function call {} failed ({}). Retrying request'
                         .format(exec_id, job_id, call_id, resp_data.replace('.', '')))

    def get_runtime_key(self, docker_image_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        service_name = self._format_service_name(docker_image_name, runtime_memory)
        runtime_key = os.path.join(self.cluster, self.namespace, service_name)

        return runtime_key
