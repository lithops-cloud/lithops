#
# (C) Copyright IBM Corp. 2020
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
import sys
import shutil
import subprocess as sp

from lithops.utils import version_str
from lithops.version import __version__

RUNTIME_NAME = 'lithops-codeengine'

DOCKER_PATH = shutil.which('docker')

RUNTIME_TIMEOUT_DEFAULT = 600  # Default: 600 seconds => 10 minutes
RUNTIME_MEMORY_DEFAULT = 128  # Default memory: 256 MB
MAX_CONCURRENT_WORKERS = 250
CPU_DEFAULT = 1  # default number of CPU

DEFAULT_API_VERSION = 'codeengine.cloud.ibm.com/v1beta1'
DEFAULT_GROUP = "codeengine.cloud.ibm.com"
DEFAULT_VERSION = "v1beta1"

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_codeengine.zip')


DEFAULT_DOCKERFILE = """
RUN apt-get update && apt-get install -y \
        zip \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade setuptools six pip \
    && pip install --no-cache-dir \
        gunicorn==19.9.0 \
        pika==0.13.1 \
        flask \
        gevent \
        glob2 \
        ibm-cos-sdk \
        redis \
        requests \
        PyYAML \
        kubernetes \
        numpy

ENV CONCURRENCY 4
ENV TIMEOUT 600
ENV PYTHONUNBUFFERED TRUE

# Copy Lithops proxy and lib to the container image.
ENV APP_HOME /lithops
WORKDIR $APP_HOME

COPY lithops_codeengine.zip .
RUN unzip lithops_codeengine.zip && rm lithops_codeengine.zip
"""


def load_config(config_data):
    if 'code_engine' not in config_data:
        config_data['code_engine'] = {}

    if 'runtime_cpu' not in config_data['code_engine']:
        config_data['code_engine']['runtime_cpu'] = CPU_DEFAULT

    if 'runtime_memory' not in config_data['serverless']:
        config_data['serverless']['runtime_memory'] = RUNTIME_MEMORY_DEFAULT
    if 'runtime_timeout' not in config_data['serverless']:
        config_data['serverless']['runtime_timeout'] = RUNTIME_TIMEOUT_DEFAULT

    if 'runtime' not in config_data['serverless']:
        if 'docker_user' not in config_data['code_engine']:
            cmd = "{} info".format(DOCKER_PATH)
            docker_user_info = sp.check_output(cmd, shell=True, encoding='UTF-8',
                                               stderr=sp.STDOUT)
            for line in docker_user_info.splitlines():
                if 'Username' in line:
                    _, useranme = line.strip().split(':')
                    config_data['code_engine']['docker_user'] = useranme.strip()
                    break

        if 'docker_user' not in config_data['code_engine']:
            raise Exception('You must provide "docker_user" param in config '
                            'or execute "docker login"')

        docker_user = config_data['code_engine']['docker_user']
        python_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'dev' in __version__ else __version__.replace('.', '')
        runtime_name = '{}/{}-v{}:{}'.format(docker_user, RUNTIME_NAME, python_version, revision)
        config_data['serverless']['runtime'] = runtime_name

    config_data['serverless']['remote_invoker'] = True

    if 'workers' not in config_data['lithops'] or \
       config_data['lithops']['workers'] > MAX_CONCURRENT_WORKERS:
        config_data['lithops']['workers'] = MAX_CONCURRENT_WORKERS
