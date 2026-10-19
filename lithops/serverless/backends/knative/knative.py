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
import json
import time
import base64
import hashlib
import logging
import requests
from datetime import datetime, timezone
from urllib.parse import urlparse
from kubernetes import client
from kubernetes.config import load_kube_config, load_incluster_config, \
    list_kube_config_contexts, KUBE_CONFIG_DEFAULT_LOCATION
from kubernetes.client.rest import ApiException

from lithops import utils
from lithops.version import __version__
from lithops.constants import COMPUTE_CLI_MSG

from . import config


logger = logging.getLogger(__name__)

REGISTRY_SECRET = 'lithops-regcred'

# Answers of the ingress and the activator to a request that never reached a
# container, so it can be sent again. Any other error may come from a call
# that already started, and sending it again would run it twice
RETRY_STATUS_CODES = (429, 503)

# Waiting reasons of a container whose image can never be pulled as it is
IMAGE_PULL_ERRORS = ('ErrImagePull', 'ImagePullBackOff', 'InvalidImageName')


def _api_error(e):
    """The message of a failed kube API request, such as a webhook rejection"""
    try:
        return json.loads(e.body)['message']
    except Exception:
        return str(e)


def _ready_condition(service):
    """The Ready condition of a Knative service, or None while it has none"""
    for condition in service.get('status', {}).get('conditions', []):
        if condition.get('type') == 'Ready':
            return condition
    return None


def _service_state(service):
    """
    Whether a Knative service serves its latest spec: 'ready', 'failed' or
    'pending', with the message of its Ready condition
    """
    status = service.get('status', {})
    condition = _ready_condition(service)
    message = f"{condition.get('reason', '')}: {condition.get('message', '')}" if condition else ''

    # Until the controller has seen the latest spec, the status describes
    # the previous one
    if status.get('observedGeneration') != service['metadata'].get('generation'):
        return 'pending', message
    if condition is None or condition.get('status') == 'Unknown':
        return 'pending', message
    if condition.get('status') == 'False':
        return 'failed', message
    if status.get('latestReadyRevisionName') != status.get('latestCreatedRevisionName'):
        return 'pending', message
    return 'ready', message


def _memory_mb(quantity):
    """The memory of a k8s quantity such as 512Mi or 2Gi, in MB"""
    if quantity.endswith('Gi'):
        return int(float(quantity[:-2]) * 1024)
    if quantity.endswith('Mi'):
        return int(quantity[:-2])
    return int(quantity) // (1024 * 1024)


class KnativeServingBackend:
    """
    A wrap-up around Knative Serving APIs.
    """

    def __init__(self, knative_config, internal_storage):
        self.name = 'knative'
        self.type = utils.BackendType.FAAS.value
        self.kn_config = knative_config
        self.ingress_endpoint = self.kn_config.get('ingress_endpoint')
        self.networking_layer = self.kn_config.get('networking_layer', 'kourier')

        self.kubecfg_path = self.kn_config.get('kubecfg_path', os.environ.get("KUBECONFIG"))
        self.kubecfg_path = os.path.expanduser(self.kubecfg_path or KUBE_CONFIG_DEFAULT_LOCATION)
        self.kubecfg_context = self.kn_config.get('kubecfg_context', 'default')
        self.namespace = self.kn_config.get('namespace')
        self.cluster = self.kn_config.get('cluster', 'default')

        if os.path.exists(self.kubecfg_path):
            logger.debug(f"Loading kubeconfig file: {self.kubecfg_path}")
            context = None if self.kubecfg_context == 'default' else self.kubecfg_context
            load_kube_config(config_file=self.kubecfg_path, context=context)
            contexts, current_context = list_kube_config_contexts(config_file=self.kubecfg_path)
            if context is not None:
                matches = [it for it in contexts if it['name'] == context]
                if not matches:
                    known = ', '.join(it['name'] for it in contexts) or '(none)'
                    raise Exception(
                        f'Kubernetes context {context!r} was not found in '
                        f'{self.kubecfg_path}. Known contexts: {known}'
                    )
                current_context = matches[0]
            ctx_context = current_context.get('context')
            self.namespace = self.namespace or ctx_context.get('namespace')
            self.cluster = ctx_context.get('cluster') or self.cluster
            logger.debug(f"Using kubeconfig context: {current_context.get('name')}")
            self.is_incluster = False
        else:
            logger.debug('kubeconfig file not found, loading incluster config')
            load_incluster_config()
            self.is_incluster = True

        self.namespace = self.namespace or 'default'
        self.kn_config['namespace'] = self.namespace
        self.kn_config['cluster'] = self.cluster

        self.custom_api = client.CustomObjectsApi()
        self.core_api = client.CoreV1Api()

        # Inside the cluster the services are reached at their cluster-local
        # address, without going through the ingress
        if self.ingress_endpoint is None and not self.is_incluster:
            self.ingress_endpoint = self._detect_ingress_endpoint()
        if self.ingress_endpoint:
            self.ingress_endpoint = self.ingress_endpoint.rstrip('/')
            logger.debug(f"Ingress endpoint: {self.ingress_endpoint}")

        self._service_urls = {}

        logger.info(f'{COMPUTE_CLI_MSG.format("Knative")} - Cluster: {self.cluster} - Namespace: {self.namespace}')

    def _detect_ingress_endpoint(self):
        """
        Finds the address of the ingress gateway of the networking layer: its
        load balancer when it has one, or else the node port of the first node
        """
        namespace, name = config.INGRESS_GATEWAYS[self.networking_layer]
        try:
            gateway = self.core_api.read_namespaced_service(name, namespace)
        except ApiException as e:
            logger.debug(f'Could not read the ingress gateway {namespace}/{name}: {_api_error(e)}')
            return None

        http_port = next((p for p in gateway.spec.ports or [] if p.port == 80), None)
        if http_port is None:
            return None

        lb_ingress = gateway.status.load_balancer.ingress if gateway.status.load_balancer else None
        if lb_ingress and (lb_ingress[0].ip or lb_ingress[0].hostname):
            return f'http://{lb_ingress[0].ip or lb_ingress[0].hostname}:{http_port.port}'

        if not http_port.node_port:
            return None
        nodes = self.core_api.list_node().items
        if not nodes:
            return None
        addresses = {addr.type: addr.address for addr in nodes[0].status.addresses or []}
        ip = addresses.get('ExternalIP') or addresses.get('InternalIP')
        return f'http://{ip}:{http_port.node_port}' if ip else None

    def _format_service_name(self, runtime_name, runtime_memory, version=__version__):
        name = f'{runtime_name}-{runtime_memory}-{version}'
        name_hash = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]

        return f'lithops-worker-{version.replace(".", "")}-{name_hash}'

    def _get_default_runtime_image_name(self):
        """
        Generates the default runtime image name
        """
        return utils.get_default_container_name(
            self.name, self.kn_config, 'lithops-knative-default'
        )

    def _get_service(self, service_name):
        return self.custom_api.get_namespaced_custom_object(
            group=config.KNATIVE_GROUP,
            version=config.KNATIVE_VERSION,
            namespace=self.namespace,
            plural="services",
            name=service_name
        )

    def _get_service_url(self, service_name):
        """
        The URL Knative routes a service at, cached for the life of the backend
        """
        if service_name not in self._service_urls:
            try:
                service = self._get_service(service_name)
            except ApiException as e:
                if e.status == 404:
                    raise Exception(f'Knative service {service_name} not found: the runtime is not deployed')
                raise Exception(f'Could not get the Knative service {service_name}: {_api_error(e)}')

            url = service.get('status', {}).get('url')
            if not url:
                raise Exception(f'Knative service {service_name} has no URL yet')
            if urlparse(url).hostname.endswith('.svc.cluster.local'):
                raise Exception(
                    f'Knative service {service_name} is only reachable inside the cluster ({url}). '
                    'Configure a domain for Knative (config-domain ConfigMap) to reach it from outside'
                )
            self._service_urls[service_name] = url

        return self._service_urls[service_name]

    def _detect_cluster_arch(self):
        """Return the dominant node architecture, or None if mixed/unknown."""
        try:
            nodes = self.core_api.list_node()
        except ApiException as e:
            logger.warning(f"Could not list cluster nodes for arch detection: {e}")
            return None
        archs = {
            n.status.node_info.architecture for n in nodes.items
            if n.status and n.status.node_info
        }
        if len(archs) == 1:
            return archs.pop()
        if len(archs) > 1:
            logger.warning(
                f"Cluster has mixed node architectures {sorted(archs)}; "
                "set 'runtime_arch' in the knative config to pick one explicitly."
            )
        return None

    def _resolve_runtime_arch(self):
        """Resolve the platform arch for `docker build --platform=linux/<arch>`."""
        configured = self.kn_config.get('runtime_arch')
        if configured:
            return configured
        detected = self._detect_cluster_arch()
        if detected in config.SUPPORTED_RUNTIME_ARCHS:
            logger.debug(f"Auto-detected cluster arch: {detected}")
            return detected
        if detected is not None:
            logger.warning(
                f"Auto-detected cluster arch '{detected}' is not supported by Lithops "
                f"(expected one of {sorted(config.SUPPORTED_RUNTIME_ARCHS)}); "
                f"falling back to '{config.DEFAULT_RUNTIME_ARCH}'."
            )
        return config.DEFAULT_RUNTIME_ARCH

    def _build_default_runtime(self, default_runtime_img_name):
        """
        Builds the default runtime
        """
        # Build default runtime using local dokcer
        dockerfile = "Dockerfile.default-knative-runtime"
        with open(dockerfile, 'w') as f:
            f.write(f"FROM python:{utils.CURRENT_PY_VERSION}-slim-bookworm\n")
            f.write(config.DEFAULT_DOCKERFILE)
        try:
            self.build_runtime(default_runtime_img_name, dockerfile)
        finally:
            os.remove(dockerfile)

    def _has_registry_credentials(self):
        return all(key in self.kn_config for key in ["docker_user", "docker_password"])

    def _create_container_registry_secret(self):
        """
        Create the container registry secret in the cluster
        (only if credentials are present in config)
        """
        if not self._has_registry_credentials():
            return

        logger.debug('Creating container registry secret')
        docker_server = self.kn_config['docker_server']
        docker_user = self.kn_config['docker_user']
        docker_password = self.kn_config['docker_password']

        cred_payload = {
            "auths": {
                docker_server: {
                    "username": docker_user,
                    "password": docker_password,
                    "auth": base64.b64encode(f'{docker_user}:{docker_password}'.encode()).decode()
                }
            }
        }

        secret = client.V1Secret(
            api_version="v1",
            data={".dockerconfigjson": base64.b64encode(json.dumps(cred_payload).encode()).decode()},
            kind="Secret",
            metadata=dict(name=REGISTRY_SECRET, namespace=self.namespace),
            type="kubernetes.io/dockerconfigjson",
        )

        try:
            self.core_api.delete_namespaced_secret(REGISTRY_SECRET, self.namespace)
        except ApiException:
            pass

        try:
            self.core_api.create_namespaced_secret(self.namespace, secret)
        except ApiException as e:
            if e.status != 409:
                raise e

    def _service_resource(self, service_name, runtime_name, runtime_memory, timeout):
        """
        The Knative service that runs a runtime: one call per container at a
        time, as many containers as max_workers, and none while it is idle
        """
        cpu = str(self.kn_config['runtime_cpu'])
        memory = f'{runtime_memory}Mi'
        labels = {
            'type': 'lithops-runtime',
            'lithops-version': __version__.replace('.', '-'),
        }

        pod_spec = {
            'containerConcurrency': 1,
            'timeoutSeconds': timeout,
            # The answer only starts once the calls finish, and Knative cuts a
            # request without one after revision-timeout-seconds (300) unless
            # told otherwise, whatever timeoutSeconds says
            'responseStartTimeoutSeconds': timeout,
            'containers': [{
                'image': runtime_name,
                # Read by the gunicorn command of the runtimes built from the
                # Dockerfiles of earlier versions
                'env': [
                    {'name': 'CONCURRENCY', 'value': '1'},
                    {'name': 'TIMEOUT', 'value': str(timeout)},
                ],
                'resources': {
                    'limits': {'memory': memory, 'cpu': cpu},
                    'requests': {'memory': memory, 'cpu': cpu},
                },
                'securityContext': {
                    'allowPrivilegeEscalation': False,
                    'capabilities': {'drop': ['ALL']},
                    'seccompProfile': {'type': 'RuntimeDefault'},
                },
            }],
        }
        if self._has_registry_credentials():
            pod_spec['imagePullSecrets'] = [{'name': REGISTRY_SECRET}]

        return {
            'apiVersion': f'{config.KNATIVE_GROUP}/{config.KNATIVE_VERSION}',
            'kind': 'Service',
            'metadata': {
                'name': service_name,
                'namespace': self.namespace,
                'labels': dict(labels),
            },
            'spec': {
                'template': {
                    'metadata': {
                        'labels': dict(labels),
                        'annotations': {
                            'autoscaling.knative.dev/min-scale': '0',
                            'autoscaling.knative.dev/max-scale': str(self.kn_config['max_workers']),
                            # One container per call in flight, not 70% more
                            'autoscaling.knative.dev/target-utilization-percentage': '100',
                            'autoscaling.knative.dev/scale-down-delay': '5m',
                            # A new revision on every deploy, so that it pulls
                            # the image the tag points to now
                            'client.knative.dev/updateTimestamp': datetime.now(timezone.utc).isoformat(),
                        },
                    },
                    'spec': pod_spec,
                },
            },
        }

    def _revision_unschedulable(self, service):
        """
        Whether the latest revision only waits for room in the cluster, which
        Knative reports as a failure although a node that frees up, or one the
        cluster autoscaler adds, fixes it
        """
        revision_name = service.get('status', {}).get('latestCreatedRevisionName')
        if not revision_name:
            return False
        try:
            revision = self.custom_api.get_namespaced_custom_object(
                group=config.KNATIVE_GROUP,
                version=config.KNATIVE_VERSION,
                namespace=self.namespace,
                plural="revisions",
                name=revision_name
            )
        except ApiException:
            return False
        condition = _ready_condition(revision)
        return condition is not None and condition.get('reason') == 'Unschedulable'

    def _image_pull_error(self, service):
        """
        Why the image of the latest revision cannot be pulled, or None. Knative
        keeps waiting for such a revision until its progress deadline, so the
        pods are looked at directly
        """
        revision_name = service.get('status', {}).get('latestCreatedRevisionName')
        if not revision_name:
            return None
        try:
            pods = self.core_api.list_namespaced_pod(
                self.namespace, label_selector=f'serving.knative.dev/revision={revision_name}'
            )
        except ApiException:
            return None
        for pod in pods.items:
            for status in pod.status.container_statuses or []:
                waiting = status.state.waiting if status.state else None
                if waiting and waiting.reason in IMAGE_PULL_ERRORS:
                    return f'{waiting.reason}: {waiting.message or ""}'.strip()
        return None

    def _wait_service_ready(self, service_name):
        """
        Waits until the latest revision of the service is ready to serve,
        raising the reason Knative gives when it cannot be
        """
        deadline = time.time() + config.SERVICE_READY_TIMEOUT
        message = ''
        while time.time() < deadline:
            service = self._get_service(service_name)
            state, message = _service_state(service)
            if state == 'ready':
                return service['status']['url']
            pull_error = self._image_pull_error(service)
            if pull_error:
                raise Exception(f'Knative service {service_name} cannot pull its image: {pull_error}')
            if state == 'failed' and not self._revision_unschedulable(service):
                raise Exception(f'Knative service {service_name} failed: {message}')
            time.sleep(2)

        raise Exception(
            f'Knative service {service_name} not ready after '
            f'{config.SERVICE_READY_TIMEOUT} seconds: {message}'
        )

    def _create_service(self, runtime_name, runtime_memory, timeout):
        """
        Creates the Knative service of a runtime, or updates it if it exists,
        and waits until it is ready
        """
        service_name = self._format_service_name(runtime_name, runtime_memory)
        logger.debug(f"Creating Knative service {service_name} in namespace {self.namespace}")
        service = self._service_resource(service_name, runtime_name, runtime_memory, timeout)

        try:
            self.custom_api.create_namespaced_custom_object(
                group=config.KNATIVE_GROUP,
                version=config.KNATIVE_VERSION,
                namespace=self.namespace,
                plural="services",
                body=service
            )
        except ApiException as e:
            if e.status != 409:
                raise Exception(f'Could not create the Knative service {service_name}: {_api_error(e)}')
            logger.debug(f'Knative service {service_name} already exists, updating it')
            # A patch, as Knative rejects a replace that drops the annotations
            # it sets on the service, such as its creator
            try:
                self.custom_api.patch_namespaced_custom_object(
                    group=config.KNATIVE_GROUP,
                    version=config.KNATIVE_VERSION,
                    namespace=self.namespace,
                    plural="services",
                    name=service_name,
                    body={'metadata': {'labels': service['metadata']['labels']}, 'spec': service['spec']}
                )
            except ApiException as e:
                raise Exception(f'Could not update the Knative service {service_name}: {_api_error(e)}')

        self._service_urls.pop(service_name, None)
        service_url = self._wait_service_ready(service_name)
        logger.debug(f'Knative service ready - URL: {service_url}')

    def _generate_runtime_meta(self, runtime_name, memory):
        """
        Extract installed Python modules from docker image
        """
        logger.info(f"Extracting metadata from: {runtime_name}")

        try:
            runtime_meta = self.invoke(runtime_name, memory, {'service_route': '/metadata'}, return_result=True)
        except Exception as e:
            raise Exception(f"Unable to extract metadata from the runtime: {e}")

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(f'Failed getting runtime metadata: {runtime_meta}')

        return runtime_meta

    def deploy_runtime(self, runtime_name, memory, timeout):
        """
        Deploys a runtime as a Knative service. The default runtime is built
        and pushed to the configured container registry first
        """
        try:
            default_image_name = self._get_default_runtime_image_name()
        except Exception:
            default_image_name = None

        if runtime_name == default_image_name:
            self._build_default_runtime(runtime_name)

        logger.info(f"Deploying runtime: {runtime_name} - Memory: {memory} Timeout: {timeout}")
        self._create_container_registry_secret()
        self._create_service(runtime_name, memory, timeout)
        try:
            runtime_meta = self._generate_runtime_meta(runtime_name, memory)
        except Exception:
            # The service is already live. Leaving it behind makes the next
            # deploy look like an update of a runtime that has no metadata
            logger.warning(f'Deleting {runtime_name}: its metadata could not be read')
            try:
                self.delete_runtime(runtime_name, memory)
            except Exception as cleanup_error:
                logger.warning(
                    f'Could not delete the Knative service for {runtime_name}: {cleanup_error}'
                )
            raise

        return runtime_meta

    def build_runtime(self, runtime_name, dockerfile, extra_args=[]):
        """
        Builds a new runtime from a Docker file and pushes it to the registry
        """
        logger.info(f'Building runtime {runtime_name} from {dockerfile or "Dockerfile"}')

        docker_path = utils.get_docker_path()

        platform = f'linux/{self._resolve_runtime_arch()}'
        if dockerfile:
            assert os.path.isfile(dockerfile), f'Cannot locate "{dockerfile}"'
            cmd = f'{docker_path} build --platform={platform} -t {runtime_name} -f {dockerfile} . '
        else:
            cmd = f'{docker_path} build --platform={platform} -t {runtime_name} . '
        cmd = cmd + ' '.join(extra_args)

        try:
            entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
            utils.create_handler_zip(config.FH_ZIP_LOCATION, entry_point, 'lithopsproxy.py')
            utils.run_command(cmd)
        finally:
            os.remove(config.FH_ZIP_LOCATION)

        docker_user = self.kn_config.get("docker_user")
        docker_password = self.kn_config.get("docker_password")
        docker_server = self.kn_config.get("docker_server")

        if docker_user and docker_password:
            logger.debug('Container registry credentials found in config. Logging in into the registry')
            utils.docker_login(docker_user, docker_password, docker_server)

        logger.debug(f'Pushing runtime {runtime_name} to container registry')
        if utils.is_podman(docker_path):
            cmd = f'{docker_path} push {runtime_name} --format docker --remove-signatures'
        else:
            cmd = f'{docker_path} push {runtime_name}'
        utils.run_command(cmd)

        logger.debug('Building done!')

    def delete_runtime(self, runtime_name, memory, version=__version__):
        service_name = self._format_service_name(runtime_name, memory, version)
        logger.info(f'Deleting runtime: {service_name}')
        self._service_urls.pop(service_name, None)
        try:
            # Foreground, so the service is gone only once its configuration,
            # route and revisions are: a service created again with the same
            # name would otherwise find them still there, owned by the old one
            self.custom_api.delete_namespaced_custom_object(
                group=config.KNATIVE_GROUP,
                version=config.KNATIVE_VERSION,
                namespace=self.namespace,
                plural="services",
                name=service_name,
                body=client.V1DeleteOptions(propagation_policy='Foreground')
            )
        except ApiException as e:
            if e.status == 404:
                return
            raise Exception(f'Could not delete the Knative service {service_name}: {_api_error(e)}')

        deadline = time.time() + config.SERVICE_READY_TIMEOUT
        while time.time() < deadline:
            try:
                self._get_service(service_name)
            except ApiException as e:
                if e.status == 404:
                    return
                raise
            time.sleep(1)
        logger.warning(f'Knative service {service_name} is still being deleted')

    def clean(self, **kwargs):
        """
        Deletes all runtimes deployed in knative
        """
        for img_name, memory, version, _ in self.list_runtimes():
            self.delete_runtime(img_name, memory, version)

    def list_runtimes(self, runtime_name='all'):
        """
        List all the runtimes deployed in knative
        return: list of tuples [runtime_name, memory, version, worker_name]
        """
        knative_services = self.custom_api.list_namespaced_custom_object(
            group=config.KNATIVE_GROUP,
            version=config.KNATIVE_VERSION,
            namespace=self.namespace,
            plural="services"
        )
        runtimes = []

        for service in knative_services['items']:
            # Earlier versions only label the template, so that is where
            # the runtimes of every version are recognized
            template = service['spec']['template']
            labels = template.get('metadata', {}).get('labels') or {}
            if labels.get('type') != 'lithops-runtime':
                continue
            try:
                version = labels['lithops-version'].replace('-', '.')
                container = template['spec']['containers'][0]
                memory = _memory_mb(container['resources']['requests']['memory'])
            except (KeyError, IndexError, ValueError):
                logger.debug(f"Skipping Knative service {service['metadata']['name']}: not a Lithops runtime")
                continue
            if runtime_name in container['image'] or runtime_name == 'all':
                runtimes.append((container['image'], memory, version, service['metadata']['name']))

        return runtimes

    def invoke(self, runtime_name, memory, payload, return_result=False):
        """
        Sends the payload to the service of the runtime. The request lasts
        as long as the calls run, as it is what keeps the container up
        """
        service_name = self._format_service_name(runtime_name, memory)
        route = payload.get("service_route", '/')
        headers = {'Content-Type': 'application/json'}

        if self.is_incluster:
            url = f'http://{service_name}.{self.namespace}.svc{route}'
        else:
            service_url = self._get_service_url(service_name)
            if self.ingress_endpoint:
                # The ingress routes the request to the service by its host
                url = f'{self.ingress_endpoint}{route}'
                headers['Host'] = urlparse(service_url).netloc
            else:
                url = f'{service_url}{route}'

        exec_id = payload.get('executor_id')
        call_ids = payload.get('call_ids')
        job_id = payload.get('job_id')

        if exec_id and job_id and call_ids:
            logger.debug(
                f'{utils.log_prefix(exec_id, job_id)} - Invoking function call '
                f'{", ".join(call_ids)}'
            )
        elif exec_id and job_id:
            logger.debug(f'{utils.log_prefix(exec_id, job_id)} - Invoking function')
        else:
            logger.debug('Invoking function')

        # Some margin over the timeout of the service, which ends the request
        # with an error of its own when the calls take longer
        read_timeout = self.kn_config['runtime_timeout'] + 60
        resp = requests.post(
            url, data=json.dumps(payload, default=str),
            headers=headers, timeout=(30, read_timeout)
        )

        if resp.status_code in (200, 202):
            data = resp.json()
            return data if return_result else data["activationId"]

        if resp.status_code in RETRY_STATUS_CODES:
            logger.debug(f'Knative service {service_name} answered {resp.status_code}, retrying the request')
            return None

        if resp.status_code == 404:
            raise Exception(f'Knative service {service_name} not found at {url}: the runtime is not deployed')

        raise Exception(f'Knative service {service_name} answered {resp.status_code}: {resp.text.strip()}')

    def get_runtime_key(self, runtime_name, runtime_memory, version=__version__):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        service_name = self._format_service_name(runtime_name, runtime_memory, version)
        cluster = self.cluster.replace('https://', '').replace('http://', '')
        runtime_key = os.path.join(self.name, version, cluster, self.namespace, service_name)

        return runtime_key

    def get_runtime_info(self):
        """
        Method that returns all the relevant information about the runtime set
        in config
        """
        if 'runtime' not in self.kn_config or self.kn_config['runtime'] == 'default':
            self.kn_config['runtime'] = self._get_default_runtime_image_name()

        runtime_info = {
            'runtime_name': self.kn_config['runtime'],
            'runtime_cpu': self.kn_config['runtime_cpu'],
            'runtime_memory': self.kn_config['runtime_memory'],
            'runtime_timeout': self.kn_config['runtime_timeout'],
            'max_workers': self.kn_config['max_workers'],
        }

        return runtime_info
