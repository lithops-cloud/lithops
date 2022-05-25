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

import logging
import httplib2
import os
import time
import json

import yaml

from lithops import utils
from lithops.constants import COMPUTE_CLI_MSG
from lithops.version import __version__

from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from google.auth.transport.requests import AuthorizedSession
from googleapiclient.discovery import build

from . import config

logger = logging.getLogger(__name__)

CLOUDRUN_API_VERSION = 'v1'
SCOPES = ('https://www.googleapis.com/auth/cloud-platform',)


class GCPCloudRunBackend:

    def __init__(self, cloudrun_config, internal_storage):
        self.name = 'cloudrun'
        self.type = 'faas'
        self.cr_config = cloudrun_config
        self.credentials_path = cloudrun_config['credentials_path']
        self.service_account = cloudrun_config['service_account']
        self.project_name = cloudrun_config['project_name']
        self.region = cloudrun_config['region']

        self._invoker_sess = None
        self._invoker_sess_route = '/'
        self._service_url = None
        self._api_resource = None

        msg = COMPUTE_CLI_MSG.format('Google Cloud Run')
        logger.info(f"{msg} - Region: {self.region} - Project: {self.project_name}")

    @staticmethod
    def _format_service_name(runtime_name, runtime_memory):
        """
        Formats service name string from runtime name and memory
        """
        runtime_name = runtime_name.replace('/', '--')
        runtime_name = runtime_name.replace(':', '--')
        runtime_name = runtime_name.replace('.', '')
        runtime_name = runtime_name.replace('_', '-')
        return f'{runtime_name}--{runtime_memory}mb'

    def _get_default_runtime_image_name(self):
        """
        Generates the default runtime image name
        """
        py_version = utils.CURRENT_PY_VERSION.replace('.', '')
        return f'lithops-default-cr-runtime-v{py_version}:{__version__}'

    def _build_api_resource(self):
        """
        Instantiate and authorize admin discovery API session
        """
        if self._api_resource is None:
            logger.debug('Building admin API session')
            credentials = service_account.Credentials.from_service_account_file(self.credentials_path, scopes=SCOPES)
            http = AuthorizedHttp(credentials, http=httplib2.Http())
            self._api_resource = build(
                'run', CLOUDRUN_API_VERSION,
                http=http, cache_discovery=False,
                client_options={
                    'api_endpoint': f'https://{self.region}-run.googleapis.com'
                }
            )
        return self._api_resource

    def _build_invoker_sess(self, runtime_name, memory, route):
        """
        Instantiate and authorize invoker session for a specific service and route
        """
        if self._invoker_sess is None or route != self._invoker_sess_route:
            logger.debug('Building invoker session')
            target = self._get_service_endpoint(runtime_name, memory) + route
            credentials = (service_account
                           .IDTokenCredentials
                           .from_service_account_file(self.credentials_path, target_audience=target))
            self._invoker_sess = AuthorizedSession(credentials)
            self._invoker_sess_route = route
        return self._invoker_sess

    def _get_service_endpoint(self, runtime_name, memory):
        """
        Gets service endpoint URL from runtime name and memory
        """
        if self._service_url is None:
            logger.debug('Getting service endpoint')
            svc_name = self._format_service_name(runtime_name, memory)
            res = self._build_api_resource().namespaces().services().get(
                name=f'namespaces/{self.project_name}/services/{svc_name}'
            ).execute()
            self._service_url = res['status']['url']
        return self._service_url

    def _format_image_name(self, runtime_name):
        """
        Formats GCR image name from runtime name
        """
        country = self.region.split('-')[0]
        return f'{country}.gcr.io/{self.project_name}/{runtime_name}'

    def _unformat_image_name(self, image_name):
        """
        Parse service string name into runtime name and memory
        :return: Tuple of (runtime_name, runtime_memory)
        """
        runtime_name = image_name.split('/', 2)[2]
        return runtime_name

    def _build_default_runtime(self, runtime_name):
        """
        Builds the default runtime
        """
        logger.debug(f'Building default {runtime_name} runtime')
        # Build default runtime using local dokcer
        dockerfile = "Dockefile.default-kn-runtime"
        with open(dockerfile, 'w') as f:
            f.write(f"FROM python:{utils.CURRENT_PY_VERSION}-slim-buster\n")
            f.write(config.DEFAULT_DOCKERFILE)
        try:
            self.build_runtime(runtime_name, dockerfile)
        finally:
            os.remove(dockerfile)

    def _generate_runtime_meta(self, runtime_name, memory):
        """
        Extract installed Python modules from docker image
        """
        logger.info(f"Extracting metadata from: {runtime_name}")

        try:
            runtime_meta = self.invoke(
                runtime_name, memory,
                {'service_route': '/preinstalls'},
                return_result=True
            )
        except Exception as e:
            raise Exception(f"Unable to extract metadata from the runtime: {e}")

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(f'Failed getting runtime metadata: {runtime_meta}')

        logger.debug(f'Ok -- Extraced modules from {runtime_name}')
        return runtime_meta

    def invoke(self, runtime_name, memory, payload, return_result=False):
        """
        Invoke a function as a POST request to the service
        """
        exec_id = payload.get('executor_id')
        call_id = payload.get('call_id')
        job_id = payload.get('job_id')
        route = payload.get("service_route", '/')

        sess = self._build_invoker_sess(runtime_name, memory, route)

        if exec_id and job_id and call_id:
            logger.debug(f'ExecutorID {exec_id} | JobID {job_id} - Invoking function call {call_id}')
        elif exec_id and job_id:
            logger.debug(f'ExecutorID {exec_id} | JobID {job_id} - Invoking function')
        else:
            logger.debug('Invoking function')

        url = self._get_service_endpoint(runtime_name, memory) + route
        res = sess.post(url=url, data=json.dumps(payload, default=str))

        if res.status_code in (200, 202):
            data = res.json()
            if return_result:
                return data
            return data["activationId"]
        else:
            raise Exception(res.text)

    def build_runtime(self, runtime_name, dockerfile, extra_args=[]):
        logger.info(f'Building runtime {runtime_name} from {dockerfile}')

        image_name = self._format_image_name(runtime_name)

        docker_path = utils.get_docker_path()

        if dockerfile:
            assert os.path.isfile(dockerfile), f'Cannot locate "{dockerfile}"'
            cmd = f'{docker_path} build -t {image_name} -f {dockerfile} . '
        else:
            cmd = f'{docker_path} build -t {image_name} . '
        cmd = cmd+' '.join(extra_args)

        try:
            entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
            utils.create_handler_zip(config.FH_ZIP_LOCATION, entry_point, 'lithopsproxy.py')
            utils.run_command(cmd)
        finally:
            os.remove(config.FH_ZIP_LOCATION)

        logger.debug('Authorizing Docker client with GCR permissions')
        country = self.region.split('-')[0]
        cmd = f'cat {self.credentials_path} | {docker_path} login {country}.gcr.io -u _json_key --password-stdin'
        if logger.getEffectiveLevel() != logging.DEBUG:
            cmd = cmd + f" >{os.devnull} 2>&1"
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error authorizing Docker for push to GCR')

        logger.debug(f'Pushing runtime {image_name} to GCP Container Registry')
        cmd = f'{docker_path} push {image_name}'
        utils.run_command(cmd)

    def _create_service(self, runtime_name, runtime_memory, timeout):
        """
        Creates a service in knative based on the docker_image_name and the memory provided
        """
        logger.debug("Creating Lithops runtime service in Google Cloud Run")
        
        img_name = self._format_image_name(runtime_name)
        service_name = self._format_service_name(runtime_name, runtime_memory)

        svc_res = yaml.safe_load(config.service_res)
        svc_res['metadata']['name'] = service_name
        svc_res['metadata']['namespace'] = self.project_name

        logger.debug(f"Service name: {service_name}")
        logger.debug(f"Namespace: {self.project_name}")

        svc_res['spec']['template']['spec']['timeoutSeconds'] = timeout
        svc_res['spec']['template']['spec']['containerConcurrency'] = 1
        svc_res['spec']['template']['spec']['serviceAccountName'] = self.service_account
        svc_res['spec']['template']['metadata']['annotations']['autoscaling.knative.dev/maxScale'] = str(self.cr_config['max_workers'])

        container = svc_res['spec']['template']['spec']['containers'][0]
        container['image'] = img_name
        container['env'][0] = {'name': 'CONCURRENCY', 'value': '1'}
        container['env'][1] = {'name': 'TIMEOUT', 'value': str(timeout)}
        container['resources']['limits']['memory'] = f'{runtime_memory}Mi'
        container['resources']['limits']['cpu'] = str(self.cr_config['runtime_cpu'])
        container['resources']['requests']['memory'] = f'{runtime_memory}Mi'
        container['resources']['requests']['cpu'] = str(self.cr_config['runtime_cpu'])

        res = self._build_api_resource().namespaces().services().create(
            parent=f'namespaces/{self.project_name}', body=svc_res
        ).execute()

        logger.info(f'Ok -- created service {service_name}')

        # Wait until service is up
        ready = False
        retry = 15
        logger.debug(f'Waiting {service_name} service to become ready')
        while not ready:
            res = self._build_api_resource().namespaces().services().get(
                name=f'namespaces/{self.project_name}/services/{service_name}'
            ).execute()

            ready = all(cond['status'] == 'True' for cond in res['status']['conditions'])

            if not ready:
                logger.debug('...')
                time.sleep(10)
                retry -= 1
                if retry == 0:
                    raise Exception(f'Maximum retries reached: {res}')
            else:
                self._service_url = res['status']['url']

        logger.info(f'Ok -- service is up at {self._service_url}')

    def deploy_runtime(self, runtime_name, memory, timeout):
        
        if runtime_name == self._get_default_runtime_image_name():
            self._build_default_runtime(runtime_name)

        logger.info(f"Deploying runtime: {runtime_name} - Memory: {memory} Timeout: {timeout}")
        self._create_service(runtime_name, memory, timeout)
        runtime_meta = self._generate_runtime_meta(runtime_name, memory)
        return runtime_meta

    def delete_runtime(self, runtime_name, memory):
        service_name = self._format_service_name(runtime_name, memory)

        logger.debug(f'Deleting runtime {runtime_name}')
        res = self._build_api_resource().namespaces().services().delete(
            name=f'namespaces/{self.project_name}/services/{service_name}'
        ).execute()
        logger.debug(f'Ok -- deleted runtime {runtime_name}')

    def clean(self):
        logger.debug('Deleting all runtimes..')

        runtimes = self.list_runtimes()
        for runtime_name, memory in runtimes:
            self.delete_runtime(runtime_name, memory)

    def list_runtimes(self, runtime_name='all'):
        logger.debug('Listing runtimes')

        res = self._build_api_resource().namespaces().services().list(
            parent=f'namespaces/{self.project_name}',
        ).execute()

        if 'items' not in res:
            return []

        logger.debug(f'Ok -- {len(res["items"])} runtimes listed')

        runtimes = []

        for item in res['items']:
            if item['spec']['template']['metadata']['labels']['type'] == 'lithops-runtime':
                container = item['spec']['template']['spec']['containers'][0]
                name = self._unformat_image_name(container['image'])
                memory = container['resources']['limits']['memory'].replace('Mi', '')
                if runtime_name == name or runtime_name == 'all':
                    runtimes.append((name, memory))

        return runtimes

    def get_runtime_key(self, runtime_name, memory):
        service_name = self._format_service_name(runtime_name, memory)
        runtime_key = os.path.join(self.name, self.project_name, service_name)
        logger.debug(f'Runtime key: {runtime_key}')

        return runtime_key

    def get_runtime_info(self):
        """
        Method that returns all the relevant information about the runtime set
        in config
        """
        if 'runtime' not in self.cr_config or self.cr_config['runtime'] == 'default':
            self.cr_config['runtime'] = self._get_default_runtime_image_name()

        runtime_info = {
            'runtime_name': self.cr_config['runtime'],
            'runtime_cpu': self.cr_config['runtime_cpu'],
            'runtime_memory': self.cr_config['runtime_memory'],
            'runtime_timeout': self.cr_config['runtime_timeout'],
            'max_workers': self.cr_config['max_workers'],
        }

        return runtime_info