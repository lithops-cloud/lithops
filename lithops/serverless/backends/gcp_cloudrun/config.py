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
import logging

logger = logging.getLogger(__name__)

REQ_PARAMS = ('region', )

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 300,  # Default: 600 seconds => 10 minutes
    'runtime_memory': 256,  # Default memory: 256 MB
    'runtime_cpu': 0.25,  # 0.25 vCPU
    'max_workers': 1000,
    'worker_processes': 1,
    'invoke_pool_threads': 100,
}

MAX_RUNTIME_MEMORY = 32768  # 32 GiB
MAX_RUNTIME_TIMEOUT = 3600  # 1 hour

AVAILABLE_RUNTIME_CPUS = [
    0.08, 0.09, 0.1, 0.11, 0.12,
    0.13, 0.14, 0.15, 0.16, 0.17,
    0.18, 0.19, 0.2, 0.21, 0.22,
    0.23, 0.24, 0.25, 0.26, 0.27,
    0.28, 0.29, 0.3, 0.31, 0.32,
    0.33, 0.34, 0.35, 0.36, 0.37,
    0.38, 0.39, 0.4, 0.41, 0.42,
    0.43, 0.44, 0.45, 0.46, 0.47,
    0.48, 0.49, 0.5, 0.51, 0.52,
    0.53, 0.54, 0.55, 0.56, 0.57,
    0.58, 0.59, 0.6, 0.61, 0.62,
    0.63, 0.64, 0.65, 0.66, 0.67,
    0.68, 0.69, 0.7, 0.71, 0.72,
    0.73, 0.74, 0.75, 0.76, 0.77,
    0.78, 0.79, 0.8, 0.81, 0.82,
    0.83, 0.84, 0.85, 0.86, 0.87,
    0.88, 0.89, 0.9, 0.91,  0.92,
    0.93, 0.94, 0.95, 0.96, 0.97,
    0.98, 0.99, 1, 2, 4, 6, 8]

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
        namegenerator \
        cryptography \
        httplib2 \
        google-cloud-storage \
        google-cloud-pubsub \
        google-api-python-client \
        gcsfs \
        google-auth


ENV PORT 8080
ENV PYTHONUNBUFFERED TRUE

ENV CONCURRENCY 1
ENV TIMEOUT 600

# Copy Lithops proxy and lib to the container image.
ENV APP_HOME /lithops
WORKDIR $APP_HOME

COPY lithops_cloudrun.zip .
RUN unzip lithops_cloudrun.zip && rm lithops_cloudrun.zip

CMD exec gunicorn --bind :$PORT --workers $CONCURRENCY --timeout $TIMEOUT lithopsproxy:proxy
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
        version: lithops_vX.X.X
      annotations:
        autoscaling.knative.dev/target: "1"
        autoscaling.knative.dev/minScale: "0"
        autoscaling.knative.dev/maxScale: "0"
        autoscaling.knative.dev/scaleDownDelay: "5m"
    spec:
      containerConcurrency: 1
      timeoutSeconds: 600
      serviceAccountName: ""
      containers:
        - image: IMAGE
          env:
            - name: CONCURRENCY
              value: "1"
            - name: TIMEOUT
              value: "600"
          resources:
            limits:
              memory: "256Mi"
              cpu: "0.5"
            requests:
              memory: "256Mi"
              cpu: "0.5"
"""


def load_config(config_data):
    if 'gcp' not in config_data:
        raise Exception("'gcp' section is mandatory in the configuration")

    for param in REQ_PARAMS:
        if param not in config_data['gcp']:
            msg = f"{param} is mandatory under 'gcp' section of the configuration"
            raise Exception(msg)

    if 'credentials_path' not in config_data['gcp']:
        if 'GOOGLE_APPLICATION_CREDENTIALS' in os.environ:
            config_data['gcp']['credentials_path'] = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')

    if 'credentials_path' in config_data['gcp']:
        config_data['gcp']['credentials_path'] = os.path.expanduser(config_data['gcp']['credentials_path'])

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
                       'Runtime timeout set to {}'.format(config_data['gcp_cloudrun']['runtime_memory'],
                                                          MAX_RUNTIME_TIMEOUT))
        config_data['gcp_cloudrun']['runtime_timeout'] = MAX_RUNTIME_TIMEOUT

    if config_data['gcp_cloudrun']['runtime_cpu'] not in AVAILABLE_RUNTIME_CPUS:
        raise Exception('{} vCPUs is not available - '
                        'choose one from {} vCPUs'.format(config_data['gcp_cloudrun']['runtime_cpu'],
                                                          AVAILABLE_RUNTIME_CPUS))
    if config_data['gcp_cloudrun']['runtime_cpu'] == 4 and config_data['gcp_cloudrun']['runtime_memory'] < 4096:
        raise Exception('For {} vCPUs, runtime memory must be at least 4096 MiB'
                        .format(config_data['gcp_cloudrun']['runtime_cpu']))

    config_data['gcp_cloudrun'].update(config_data['gcp'])
