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

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_k8s.zip')


SINGULARITYFILE_DEFAULT = """
%post
    apt-get update && apt-get install -y \
        zip redis-server curl \
        && apt-get clean \
        && rm -rf /var/lib/apt/lists/*

    pip install --upgrade setuptools six pip \
    && pip install --no-cache-dir \
        flask \
        pika \
        boto3 \
        ibm-cloud-sdk-core \
        ibm-cos-sdk \
        redis \
        gevent \
        requests \
        PyYAML \
        kubernetes \
        numpy \
        cloudpickle \
        ps-mem \
        tblib \
        psutil

%environment
    export PYTHONUNBUFFERED=TRUE
    export APP_HOME=/lithops
    cd $APP_HOME

%files
    lithops_k8s.zip /lithops/lithops_k8s.zip

%post
    cd /lithops
    unzip lithops_k8s.zip && rm lithops_k8s.zip
"""

def load_config(config_data):
    config_data['singularity']['worker_processes'] = 1

    if 'rabbitmq' in config_data:
      config_data['singularity']['amqp_url'] = config_data['rabbitmq'].get('amqp_url', False)