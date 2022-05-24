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

    @staticmethod
    def _unformat_service_name(service_name):
        """
        Parse service string name into runtime name and memory
        :return: Tuple of (runtime_name, runtime_memory)
        """
        split_service_name = service_name.split('--')
        runtime_name = split_service_name[2]
        memory = int(split_service_name[3].replace('mb', ''))
        return runtime_name, memory

    def _get_default_runtime_image_name(self):
        """
        Generates the default runtime image name
        """
        py_version = utils.CURRENT_PY_VERSION.replace('.', '')
        revision = 'latest' if 'dev' in __version__ else __version__.replace('.', '')
        return f'lithops-default-cr-runtime-v{py_version}:{revision}'

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
        logger.info("Extracting Python modules from: {}".format(runtime_name))

        try:
            runtime_meta = self.invoke(runtime_name, memory,
                                       {'service_route': '/preinstalls'}, return_result=True)
        except Exception as e:
            raise Exception("Unable to extract the preinstalled modules from the runtime: {}".format(e))

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception('Failed getting runtime metadata: {}'.format(runtime_meta))

        logger.debug('Ok -- Extraced modules from {}'.format(runtime_name))
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
            logger.debug('ExecutorID {} | JobID {} - Invoking function call {}'
                         .format(exec_id, job_id, call_id))
        elif exec_id and job_id:
            logger.debug('ExecutorID {} | JobID {} - Invoking function'
                         .format(exec_id, job_id))
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
            cmd = cmd + " >{} 2>&1".format(os.devnull)
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error authorizing Docker for push to GCR')

        logger.debug(f'Pushing runtime {image_name} to GCP Container Registry')
        cmd = f'{docker_path} push {image_name}'
        utils.run_command(cmd)

    def deploy_runtime(self, runtime_name, runtime_memory, timeout):
        if runtime_name == self._get_default_runtime_image_name():
            self._build_default_runtime(runtime_name)

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

        print(svc_res)

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
                time.sleep(15)
                retry -= 1
                if retry == 0:
                    raise Exception(f'Maximum retries reached: {res}')
            else:
                self._service_url = res['status']['url']

        logger.info('Ok -- service is up at {}'.format(self._service_url))

        runtime_meta = self._generate_runtime_meta(runtime_name, runtime_memory)
        return runtime_meta

    def delete_runtime(self, runtime_name, memory):
        service_name = self._format_service_name(runtime_name, memory)

        logger.debug('Deleting runtime {}'.format(runtime_name))
        res = self._build_api_resource().namespaces().services().delete(
            name='namespaces/{}/services/{}'.format(self.project_name, service_name)
        ).execute()
        logger.debug('Ok -- deleted runtime {}'.format(runtime_name))

    def clean(self):
        logger.debug('Deleting all runtimes..')

        runtimes = self.list_runtimes()
        for runtime_name, memory in runtimes:
            self.delete_runtime(runtime_name, memory)

    def list_runtimes(self, runtime_name='all'):
        logger.debug('Listing runtimes...')

        res = self._build_api_resource().namespaces().services().list(
            parent='namespaces/{}'.format(self.project_name),
        ).execute()

        if 'items' not in res:
            return []

        logger.debug('Ok -- {} runtimes listed'.format(len(res['items'])))

        return [self._unformat_service_name(item['metadata']['name']) for item in res['items']]

    def get_runtime_key(self, runtime_name, memory):
        service_name = self._format_service_name(runtime_name, memory)
        runtime_key = os.path.join(self.name, self.project_name, service_name)
        logger.debug('Runtime key: {}'.format(runtime_key))

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