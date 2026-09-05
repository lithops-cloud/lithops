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

import copy
import json
import os


def load_config(config_data):
    overrides = copy.deepcopy(config_data.get('gcp_pubsub') or {})
    merged = {}
    if config_data.get('gcp'):
        merged.update(config_data['gcp'])
    merged.update(overrides)
    config_data['gcp_pubsub'] = merged

    section = config_data['gcp_pubsub']
    if 'credentials_path' not in section:
        if 'GOOGLE_APPLICATION_CREDENTIALS' in os.environ:
            section['credentials_path'] = os.environ.get(
                'GOOGLE_APPLICATION_CREDENTIALS'
            )

    if 'credentials_path' in section:
        section['credentials_path'] = os.path.expanduser(
            section['credentials_path']
        )
        if 'project_name' not in section:
            try:
                with open(section['credentials_path']) as creds:
                    project = json.load(creds).get('project_id')
                if project:
                    section['project_name'] = project
            except Exception:
                pass

    if 'project_name' not in section:
        raise Exception(
            "'project_name' is mandatory under 'gcp_pubsub' or 'gcp' section "
            "of the configuration"
        )
