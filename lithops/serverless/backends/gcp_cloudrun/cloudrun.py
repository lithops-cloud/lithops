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

from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

CLOUDRUN_API_VERSION = 'v1'

SCOPES = ('https://www.googleapis.com/auth/cloud-platform',)


class GCPCloudRunBackend:
    def __init__(self, cloudrun_config, storage_config):
        self.credentials_path = cloudrun_config['credentials_path']
        self.service_account = cloudrun_config['service_account']

    def _get_auth_session(self):
        credentials = service_account.Credentials.from_service_account_file(self.credentials_path, scopes=SCOPES)
        http = httplib2.Http()
        return AuthorizedHttp(credentials, http=http)

    def _get_funct_conn(self):
        http = self._get_auth_session()
        return build('run', CLOUDRUN_API_VERSION, http=http, cache_discovery=False, client_options={'api_endpoint': 'https://us-central1-run.googleapis.com'})

    def invoke(self, runtime_name, memory, payload):
        pass

    def build_runtime(self, runtime_name, file):
        pass

    def create_runtime(self, runtime_name, memory, timeout):
        http = self._get_funct_conn()
        namespace_id = 'cloudbutton'
        body = {
            "apiVersion": 'serving.knative.dev/v1',
            "kind": 'Service',
            "metadata": {
                "name": 'p',
                "namespace": namespace_id,
            },
            "spec": {
                "template": {
                    "metadata": {
                        "name": 'p-rev',
                        "namespace": namespace_id,
                    },
                    "spec": {
                        "containerConcurrency": 1,
                        "timeoutSeconds": timeout,
                        "serviceAccountName": self.service_account,
                        "containers": [
                            {
                                "image": 'us-docker.pkg.dev/cloudrun/container/hello',
                                "resources": {
                                    "limits": {
                                    },
                                    "requests": {
                                    }
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
        res = http.namespaces().services().create(
            parent=f'namespaces/{namespace_id}',
            body=body
        ).execute()
        print(res)

    def delete_runtime(self, runtime_name, memory):
        pass

    def clean(self):
        pass

    def clear(self):
        pass

    def list_runtimes(self, runtime_name='all'):
        pass

    def get_runtime_key(self, runtime_name, memory):
        pass


# if __name__ == '__main__':
#     config = {'credentials_path': '/home/aitor-pc/Documents/cloudbutton-69b16c2f6951.json',
#               'service_account': 'cloudbutton-executor@cloudbutton.iam.gserviceaccount.com'}
#     be = GCPCloudRunBackend(config, None)
#     be.create_runtime('test', 256, 60)
