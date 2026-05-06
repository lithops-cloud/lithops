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

import copy
import os
import logging

logger = logging.getLogger(__name__)

CLOUDRUN_API_VERSION = 'v1'
SCOPES = ('https://www.googleapis.com/auth/cloud-platform',)

# Defaults align with Cloud Run service limits (memory, CPU, request timeout).
# See https://cloud.google.com/run/docs/configuring/services/memory-limits
# and https://cloud.google.com/run/docs/configuring/services/cpu
DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 300,  # seconds (max 3600 for services)
    'runtime_memory': 256,  # MiB (max 32768)
    'runtime_cpu': 0.25,  # vCPU: 0.08–<1 in 0.001 steps, or 1, 2, 4, 6, 8
    'max_workers': 100,
    'min_workers': 0,
    'worker_processes': 1,
    'invoke_pool_threads': 100,
    'trigger': 'https',
    # Substring marker so utils.get_default_container_name() builds an Artifact Registry image name.
    'docker_server': 'pkg.dev',
    'artifact_registry_repository': 'lithops',
}

MAX_RUNTIME_MEMORY = 32768  # 32 GiB (Cloud Run service maximum)
MAX_RUNTIME_TIMEOUT = 3600  # 60 minutes (Cloud Run request timeout maximum)


def is_valid_cloud_run_cpu(cpu):
    """
    True if cpu is allowed for Cloud Run: 1, 2, 4, 6, 8, or 0.08–<1.00 in 0.001 increments.
    """
    if cpu in (1, 2, 4, 6, 8):
        return True
    try:
        c = float(cpu)
    except (TypeError, ValueError):
        return False
    if not (0.08 <= c < 1.0):
        return False
    r = round(c, 3)
    if abs(c - r) > 1e-5:
        return False
    n = int(round((r - 0.08) / 0.001 + 1e-9))
    expected = round(0.08 + n * 0.001, 3)
    return abs(r - expected) < 1e-5 and 0 <= n <= 919


FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_cloudrun.zip')

DEFAULT_DOCKERFILE = """
RUN apt-get update && apt-get install -y \
        zip \
        && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade --ignore-installed setuptools six pip \
    && pip install --upgrade --no-cache-dir --ignore-installed \
        wheel \
        gunicorn \
        pika \
        flask \
        gevent \
        redis \
        requests \
        PyYAML \
        kubernetes \
        numpy \
        cloudpickle \
        ps-mem \
        tblib \
        cryptography \
        httplib2 \
        google-cloud-storage \
        google-cloud-pubsub \
        google-api-python-client \
        gcsfs \
        google-auth \
        psutil


ENV PORT=8080
ENV PYTHONUNBUFFERED=TRUE

ENV CONCURRENCY=1
ENV TIMEOUT=600

# Copy Lithops proxy and lib to the container image.
ENV APP_HOME=/lithops
WORKDIR $APP_HOME

COPY lithops_cloudrun.zip .
RUN unzip lithops_cloudrun.zip && rm lithops_cloudrun.zip

CMD ["sh", "-c", "exec gunicorn --bind :$PORT --workers $CONCURRENCY --timeout $TIMEOUT lithopsproxy:proxy"]
"""

service_res = """
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: lithops-runtime-name
  namespace: default
  annotations:
    run.googleapis.com/launch-stage: BETA
spec:
  template:
    metadata:
      labels:
        type: lithops-runtime
        lithops-version: x-y-z
      annotations:
        autoscaling.knative.dev/target: "1"
        autoscaling.knative.dev/minScale: "0"
        autoscaling.knative.dev/maxScale: "0"
        autoscaling.knative.dev/scaleDownDelay: "5m"
    spec:
      containerConcurrency: 1
      timeoutSeconds: 300
      serviceAccountName: ""
      containers:
        - image: IMAGE
          env:
            - name: CONCURRENCY
              value: "1"
            - name: TIMEOUT
              value: "300"
          resources:
            limits:
              memory: "256Mi"
              cpu: "0.25"
            requests:
              memory: "256Mi"
              cpu: "0.25"
"""


def load_config(config_data):
    if 'gcp' not in config_data:
        raise Exception("'gcp' section is mandatory in the configuration")

    if 'credentials_path' not in config_data['gcp']:
        if 'GOOGLE_APPLICATION_CREDENTIALS' in os.environ:
            config_data['gcp']['credentials_path'] = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')

    if 'credentials_path' in config_data['gcp']:
        config_data['gcp']['credentials_path'] = os.path.expanduser(config_data['gcp']['credentials_path'])
    if 'credentials_path' not in config_data['gcp']:
        raise Exception("'credentials_path' parameter is mandatory under the 'gcp' section for gcp_cloudrun")
    if not os.path.isfile(config_data['gcp']['credentials_path']):
        raise Exception(
            'A valid "gcp.credentials_path" service account JSON file is required '
            f'({config_data["gcp"]["credentials_path"]})'
        )

    temp = copy.deepcopy(config_data['gcp_cloudrun'])
    config_data['gcp_cloudrun'].update(config_data['gcp'])
    config_data['gcp_cloudrun'].update(temp)

    if 'region' not in config_data['gcp_cloudrun']:
        raise Exception("'region' parameter is mandatory under 'gcp_cloudrun' or 'gcp' section of the configuration")

    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['gcp_cloudrun']:
            config_data['gcp_cloudrun'][key] = DEFAULT_CONFIG_KEYS[key]

    config_data['gcp_cloudrun']['invoke_pool_threads'] = config_data['gcp_cloudrun']['max_workers']

    if config_data['gcp_cloudrun']['runtime_memory'] > MAX_RUNTIME_MEMORY:
        logger.warning('Runtime memory {} exceeds maximum - '
                       'Runtime memory set to {}'.format(config_data['gcp_cloudrun']['runtime_memory'],
                                                         MAX_RUNTIME_MEMORY))
        config_data['gcp_cloudrun']['runtime_memory'] = MAX_RUNTIME_MEMORY

    if config_data['gcp_cloudrun']['runtime_timeout'] > MAX_RUNTIME_TIMEOUT:
        logger.warning('Runtime timeout {} exceeds maximum - '
                       'Runtime timeout set to {}'.format(config_data['gcp_cloudrun']['runtime_timeout'],
                                                          MAX_RUNTIME_TIMEOUT))
        config_data['gcp_cloudrun']['runtime_timeout'] = MAX_RUNTIME_TIMEOUT

    if not is_valid_cloud_run_cpu(config_data['gcp_cloudrun']['runtime_cpu']):
        raise Exception(
            '{} vCPU is not valid for Cloud Run — use 1, 2, 4, 6, 8, or '
            '0.08 to less than 1.0 in steps of 0.001'.format(config_data['gcp_cloudrun']['runtime_cpu'])
        )
    if config_data['gcp_cloudrun']['runtime_cpu'] == 4 and config_data['gcp_cloudrun']['runtime_memory'] < 4096:
        raise Exception('For {} vCPUs, runtime memory must be at least 4096 MiB'
                        .format(config_data['gcp_cloudrun']['runtime_cpu']))

    if 'region' not in config_data['gcp']:
        config_data['gcp']['region'] = config_data['gcp_cloudrun']['region']
