#
# (C) Copyright IBM Corp. 2019
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

KNATIVE_GROUP = 'serving.knative.dev'
KNATIVE_VERSION = 'v1'

DEFAULT_CONFIG_KEYS = {
    'runtime_timeout': 600,  # Default: 600 seconds => 10 minutes
    'runtime_memory': 512,  # Default memory: 512 MB
    'runtime_cpu': 1,  # 1 vCPU
    'max_workers': 100,
    'worker_processes': 1,
    'docker_server': 'docker.io',
    'networking_layer': 'kourier',
}

# Namespace and name of the k8s Service that exposes the ingress gateway of
# each networking layer Knative supports, as their install manifests create it
INGRESS_GATEWAYS = {
    'kourier': ('kourier-system', 'kourier'),
    'istio': ('istio-system', 'istio-ingressgateway'),
    'contour': ('contour-external', 'envoy'),
}

SUPPORTED_RUNTIME_ARCHS = {'amd64', 'arm64'}
DEFAULT_RUNTIME_ARCH = 'amd64'

# How long a new or updated service has to become ready. Longer than the
# scale-down-delay of the services, so that an update waits until the
# containers of the previous revision free their place in the cluster
SERVICE_READY_TIMEOUT = 600

FH_ZIP_LOCATION = os.path.join(os.getcwd(), 'lithops_knative.zip')

DEFAULT_DOCKERFILE = """
RUN apt-get update && apt-get install -y --no-install-recommends \\
        zip unzip \\
        && apt-get clean \\
        && rm -rf /var/lib/apt/lists/*

# Pin setuptools<81 (PEP 517 build envs included) so legacy sdists that
# import pkg_resources still build.
RUN echo 'setuptools<81' > /tmp/constraints.txt
ENV PIP_CONSTRAINT=/tmp/constraints.txt

RUN pip install --no-cache-dir 'setuptools<81' six wheel \\
    && pip install --no-cache-dir \\
        gunicorn \\
        flask \\
        pika \\
        boto3 \\
        ibm-cloud-sdk-core \\
        ibm-cos-sdk \\
        google-cloud-storage \\
        google-cloud-pubsub \\
        azure-storage-blob \\
        azure-storage-queue \\
        redis \\
        requests \\
        PyYAML \\
        kubernetes \\
        numpy \\
        cloudpickle \\
        ps-mem \\
        tblib \\
        psutil

ENV PORT=8080
ENV PYTHONUNBUFFERED=TRUE
ENV APP_HOME=/lithops

RUN groupadd -g 1000 lithops && useradd -m -u 1000 -g 1000 lithops

WORKDIR $APP_HOME

COPY lithops_knative.zip .
RUN unzip lithops_knative.zip && rm lithops_knative.zip && chown -R lithops:lithops $APP_HOME

USER 1000:1000

# One request at a time, as the service admits one per container. Knative
# and the Lithops worker enforce the timeout, so gunicorn does not
CMD ["sh", "-c", "exec gunicorn --bind :$PORT --workers 1 --threads 1 --timeout 0 lithopsproxy:proxy"]
"""


def load_config(config_data):
    for key in DEFAULT_CONFIG_KEYS:
        if key not in config_data['knative']:
            config_data['knative'][key] = DEFAULT_CONFIG_KEYS[key]

    networking_layer = config_data['knative']['networking_layer']
    if networking_layer not in INGRESS_GATEWAYS:
        raise Exception(
            f"'networking_layer' under 'knative' must be one of "
            f"{sorted(INGRESS_GATEWAYS)}, got '{networking_layer}'"
        )

    arch = config_data['knative'].get('runtime_arch')
    if arch is not None and arch not in SUPPORTED_RUNTIME_ARCHS:
        raise Exception(
            f"'runtime_arch' under 'knative' must be one of "
            f"{sorted(SUPPORTED_RUNTIME_ARCHS)} or null, got '{arch}'"
        )

    # One invocation thread per worker, not a user setting: each call holds
    # its request open until the function finishes
    config_data['knative']['invoke_pool_threads'] = config_data['knative']['max_workers']

    if 'runtime' in config_data['knative']:
        runtime = config_data['knative']['runtime']
        registry = config_data['knative']['docker_server']
        if runtime.count('/') == 1 and registry not in runtime:
            config_data['knative']['runtime'] = f'{registry}/{runtime}'
