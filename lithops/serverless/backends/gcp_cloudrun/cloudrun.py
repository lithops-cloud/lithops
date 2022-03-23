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
import sys
import time
import json

from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from google.auth.transport.requests import AuthorizedSession
from googleapiclient.discovery import build

from ..knative import config as kconfig
from . import config as cr_config
from ....utils import version_str, create_handler_zip
from ....version import __version__

logger = logging.getLogger(__name__)

CLOUDRUN_API_VERSION = 'v1'
SCOPES = ('https://www.googleapis.com/auth/cloud-platform',)


class GCPCloudRunBackend:

    def __init__(self, cloudrun_config, internal_storage):
        self.name = 'cloudrun'
        self.type = 'faas'
        self.credentials_path = cloudrun_config['credentials_path']
        self.service_account = cloudrun_config['service_account']
        self.project_name = cloudrun_config['project_name']
        self.region = cloudrun_config['region']
        self.runtime_cpu = cloudrun_config['runtime_cpu']
        self.workers = cloudrun_config['max_workers']

        self._invoker_sess = None
        self._invoker_sess_route = '/'
        self._service_url = None
        self._api_resource = None

    @staticmethod
    def _format_service_name(runtime_name, runtime_memory):
        """
        Formats service name string from runtime name and memory
        """
        return 'lithops--{}--{}--{}mb'.format(__version__.replace('.', '-'),
                                              runtime_name.replace('.', ''),
                                              runtime_memory)

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

    def _build_api_resource(self):
        """
        Instantiate and authorize admin discovery API session
        """
        if self._api_resource is None:
            logger.debug('Building admin API session')
            credentials = service_account.Credentials.from_service_account_file(self.credentials_path, scopes=SCOPES)
            http = AuthorizedHttp(credentials, http=httplib2.Http())
            self._api_resource = build('run', CLOUDRUN_API_VERSION,
                                       http=http,
                                       cache_discovery=False,
                                       client_options={
                                           'api_endpoint': 'https://{}-run.googleapis.com'.format(self.region)
                                       })
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
            res = self._build_api_resource().namespaces().services().get(
                name='namespaces/{}/services/{}'.format(self.project_name,
                                                        self._format_service_name(runtime_name, memory))
            ).execute()
            self._service_url = res['status']['url']
        return self._service_url

    def _format_image_name(self, runtime_name):
        """
        Formats GCR image name from runtime name
        """
        runtime_name = runtime_name.replace('.', '').replace('_', '-')
        revision = 'latest' if 'dev' in __version__ else __version__.replace('.', '')
        return 'gcr.io/{}/lithops-cloudrun-{}:{}'.format(self.project_name, runtime_name, revision)

    def _build_default_runtime(self):
        """
        Builds the default runtime
        """
        logger.debug('Building default {} runtime'.format(cr_config.DEFAULT_RUNTIME_NAME))
        if os.system('{} --version >{} 2>&1'.format(kconfig.DOCKER_PATH, os.devnull)) == 0:
            # Build default runtime using local dokcer
            python_version = version_str(sys.version_info)
            dockerfile = "Dockefile.default-knative-runtime"
            with open(dockerfile, 'w') as f:
                f.write("FROM python:{}-slim-buster\n".format(python_version))
                f.write(cr_config.DEFAULT_DOCKERFILE)
            self.build_runtime(cr_config.DEFAULT_RUNTIME_NAME, dockerfile)
            os.remove(dockerfile)
        else:
            raise Exception('Docker CLI not found')

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
        logger.debug('Building a new docker image from Dockerfile')

        image_name = self._format_image_name(runtime_name)

        logger.debug('Docker image name: {}'.format(image_name))

        entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
        create_handler_zip(kconfig.FH_ZIP_LOCATION, entry_point, 'lithopsproxy.py')

        if dockerfile:
            cmd = '{} build -t {} -f {} . '.format(kconfig.DOCKER_PATH,
                                                   image_name,
                                                   dockerfile)
        else:
            cmd = '{} build -t {} . '.format(kconfig.DOCKER_PATH, image_name)

        cmd = cmd+' '.join(extra_args)

        logger.info('Building Docker image')
        if logger.getEffectiveLevel() != logging.DEBUG:
            cmd = cmd + " >{} 2>&1".format(os.devnull)

        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error building the runtime')

        os.remove(kconfig.FH_ZIP_LOCATION)

        logger.debug('Authorizing Docker client with GCR permissions'.format(image_name))
        cmd = 'cat {} | docker login -u _json_key --password-stdin https://gcr.io'.format(self.credentials_path)
        if logger.getEffectiveLevel() != logging.DEBUG:
            cmd = cmd + " >{} 2>&1".format(os.devnull)
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error authorizing Docker for push to GCR')

        logger.info('Pushing Docker image {} to GCP Container Registry'.format(image_name))
        cmd = '{} push {}'.format(kconfig.DOCKER_PATH, image_name)
        if logger.getEffectiveLevel() != logging.DEBUG:
            cmd = cmd + " >{} 2>&1".format(os.devnull)
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error pushing the runtime to the container registry')

    def deploy_runtime(self, runtime_name, memory, timeout):
        if runtime_name == cr_config.DEFAULT_RUNTIME_NAME:
            self._build_default_runtime()

        img_name = self._format_image_name(runtime_name)
        service_name = self._format_service_name(runtime_name, memory)

        body = {
            "apiVersion": 'serving.knative.dev/v1',
            "kind": 'Service',
            "metadata": {
                "name": service_name,
                "namespace": self.project_name,
            },
            "spec": {
                "template": {
                    "metadata": {
                        "name": '{}-rev'.format(service_name),
                        "namespace": self.project_name,
                        "annotations": {
                            "autoscaling.knative.dev/minScale": "0",
                            "autoscaling.knative.dev/maxScale": str(self.workers)
                        }
                    },
                    "spec": {
                        "containerConcurrency": 1,
                        "timeoutSeconds": timeout,
                        "serviceAccountName": self.service_account,
                        "containers": [
                            {
                                "image": img_name,
                                "resources": {
                                    "limits": {
                                        "memory": "{}Mi".format(memory),
                                        "cpu": str(self.runtime_cpu)
                                    },
                                },
                            }
                        ],
                    }
                },
                "traffic": [
                    {
                        "percent": 100,
                        "latestRevision": True
                    }
                ]
            }
        }

        res = self._build_api_resource().namespaces().services().create(
            parent='namespaces/{}'.format(self.project_name),
            body=body
        ).execute()

        logger.info('Ok -- created service {}'.format(service_name))

        # Wait until service is up
        ready = False
        retry = 15
        while not ready:
            res = self._build_api_resource().namespaces().services().get(
                name='namespaces/{}/services/{}'.format(self.project_name,
                                                        self._format_service_name(runtime_name, memory))
            ).execute()

            ready = all(cond['status'] == 'True' for cond in res['status']['conditions'])

            if not ready:
                logger.debug('Waiting until service is up...')
                time.sleep(10)
                retry -= 1
                if retry == 0:
                    raise Exception('Maximum retries reached: {}'.format(res))
            else:
                self._service_url = res['status']['url']

        logger.info('Ok -- service is up at {}'.format(self._service_url))

        runtime_meta = self._generate_runtime_meta(runtime_name, memory)
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
