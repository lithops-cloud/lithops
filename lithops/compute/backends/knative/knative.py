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
import re
import sys
import ssl
import json
import time
import yaml
import urllib3
import logging
import requests
import http.client
from urllib.parse import urlparse
from kubernetes import client, config, watch
from lithops.utils import version_str
from lithops.version import __version__
from lithops.config import CACHE_DIR, load_yaml_config, dump_yaml_config
from lithops.compute.utils import create_function_handler_zip
from . import config as kconfig

urllib3.disable_warnings()
logging.getLogger('kubernetes').setLevel(logging.CRITICAL)
logging.getLogger('urllib3.connectionpool').setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)


class KnativeServingBackend:
    """
    A wrap-up around Knative Serving APIs.
    """

    def __init__(self, knative_config, storage_config):
        self.log_active = logger.getEffectiveLevel() != logging.WARNING
        self.name = 'knative'
        self.knative_config = knative_config
        self.istio_endpoint = self.knative_config.get('istio_endpoint')

        # k8s config can be incluster, in ~/.kube/config or generate kube-config.yaml file and
        # set env variable KUBECONFIG=<path-to-kube-confg>
        try:
            config.load_kube_config()
            current_context = config.list_kube_config_contexts()[1].get('context')
            self.namespace = current_context.get('namespace', 'default')
            self.cluster = current_context.get('cluster')
            self.knative_config['namespace'] = self.namespace
            self.knative_config['cluster'] = self.cluster
            self.is_incluster = False
        except Exception:
            config.load_incluster_config()
            self.namespace = self.knative_config.get('namespace', 'default')
            self.cluster = self.knative_config.get('cluster', 'default')
            self.is_incluster = True

        self.api = client.CustomObjectsApi()
        self.v1 = client.CoreV1Api()

        if self.istio_endpoint is None:
            try:
                ingress = self.v1.read_namespaced_service('istio-ingressgateway', 'istio-system')
                http_port = list(filter(lambda port: port.port == 80, ingress.spec.ports))[0].node_port
                # https_port = list(filter(lambda port: port.port == 443, ingress.spec.ports))[0].node_port

                if ingress.status.load_balancer.ingress is not None:
                    # get loadbalancer ip
                    ip = ingress.status.load_balancer.ingress[0].ip
                else:
                    # for minikube or a baremetal cluster that has no external load balancer
                    node = self.v1.list_node()
                    ip = node.items[0].status.addresses[0].address

                self.istio_endpoint = 'http://{}:{}'.format(ip, http_port)
                self.knative_config['istio_endpoint'] = self.istio_endpoint
            except Exception:
                logger.info("istio-ingressgateway endpoint not found")

        if 'service_host_suffix' not in self.knative_config:
            self.serice_host_filename = os.path.join(CACHE_DIR, 'knative', self.cluster, 'service_host')
            self.service_host_suffix = None
            if os.path.exists(self.serice_host_filename):
                serice_host_data = load_yaml_config(self.serice_host_filename)
                self.service_host_suffix = serice_host_data['service_host_suffix']
                self.knative_config['service_host_suffix'] = self.service_host_suffix
        else:
            self.service_host_suffix = self.knative_config['service_host_suffix']

        logger.debug('Loaded service host suffix: {}'.format(self.service_host_suffix))

        if self.istio_endpoint:
            log_msg = 'Lithops v{} init for Knative - Istio Endpoint: {}'.format(__version__, self.istio_endpoint)
        else:
            log_msg = 'Lithops v{} init for Knative'.format(__version__)
        if not self.log_active:
            print(log_msg)
        logger.info(log_msg)

    def _format_service_name(self, runtime_name, runtime_memory):
        runtime_name = runtime_name.replace('/', '--').replace(':', '--')
        return '{}--{}mb'.format(runtime_name, runtime_memory)

    def _unformat_service_name(self, service_name):
        runtime_name, memory = service_name.rsplit('--', 1)
        image_name = runtime_name.replace('--', '/', 1)
        image_name = image_name.replace('--', ':', -1)
        return image_name, int(memory.replace('mb', ''))

    def _get_default_runtime_image_name(self):
        docker_user = self.knative_config['docker_user']
        python_version = version_str(sys.version_info).replace('.', '')
        revision = 'latest' if 'SNAPSHOT' in __version__ else __version__.replace('.', '')
        return '{}/{}-v{}:{}'.format(docker_user, kconfig.RUNTIME_NAME_DEFAULT, python_version, revision)

    def _get_service_host(self, service_name):
        """
        gets the service host needed for the invocation
        """
        logger.debug('Getting service host for: {}'.format(service_name))
        try:
            #t0 = time.time()
            svc = self.api.get_namespaced_custom_object(
                        group="serving.knative.dev",
                        version="v1alpha1",
                        name=service_name,
                        namespace=self.namespace,
                        plural="services"
                )
            if svc is not None:
                service_host = svc['status']['url'][7:]
            else:
                raise Exception('Unable to get service details from {}'.format(service_name))
            #print(time.time()-t0)
        except Exception as e:
            if json.loads(e.body)['code'] == 404:
                log_msg = 'Knative service: resource "{}" Not Found'.format(service_name)
                raise(log_msg)
            else:
                raise(e)

        logger.debug('Service host: {}'.format(service_host))
        return service_host

    def _create_account_resources(self):
        """
        Creates the secret to access to the docker hub and the ServiceAcount
        """
        logger.debug("Creating Tekton account resources: Secret and ServiceAccount")
        string_data = {'username': self.knative_config['docker_user'],
                       'password': self.knative_config['docker_token']}
        secret_res = yaml.safe_load(kconfig.secret_res)
        secret_res['stringData'] = string_data

        if self.knative_config['docker_repo'] != kconfig.DOCKER_REPO_DEFAULT:
            secret_res['metadata']['annotations']['tekton.dev/docker-0'] = self.knative_config['docker_repo']

        account_res = yaml.safe_load(kconfig.account_res)
        secret_res_name = secret_res['metadata']['name']
        account_res_name = account_res['metadata']['name']

        try:
            self.v1.delete_namespaced_secret(secret_res_name, self.namespace)
            self.v1.delete_namespaced_service_account(account_res_name, self.namespace)
        except Exception:
            # account resource Not Found - Not deleted
            pass

        self.v1.create_namespaced_secret(self.namespace, secret_res)
        self.v1.create_namespaced_service_account(self.namespace, account_res)

    def _create_build_resources(self):
        logger.debug("Creating Tekton build resources: PipelineResource and Task")
        git_res = yaml.safe_load(kconfig.git_res)
        git_res_name = git_res['metadata']['name']

        task_def = yaml.safe_load(kconfig.task_def)
        task_name = task_def['metadata']['name']

        git_url_param = {'name': 'url', 'value': self.knative_config['git_url']}
        git_rev_param = {'name': 'revision', 'value': self.knative_config['git_rev']}
        params = [git_url_param, git_rev_param]
        git_res['spec']['params'] = params

        logger.debug('Setting git url to: {}'.format(self.knative_config['git_url']))
        logger.debug('Setting git rev to: {}'.format(self.knative_config['git_rev']))

        try:
            self.api.delete_namespaced_custom_object(
                    group="tekton.dev",
                    version="v1alpha1",
                    name=task_name,
                    namespace=self.namespace,
                    plural="tasks",
                    body=client.V1DeleteOptions()
                )
        except Exception:
            # ksvc resource Not Found  - Not deleted
            pass

        try:
            self.api.delete_namespaced_custom_object(
                    group="tekton.dev",
                    version="v1alpha1",
                    name=git_res_name,
                    namespace=self.namespace,
                    plural="pipelineresources",
                    body=client.V1DeleteOptions()
                )
        except Exception:
            # ksvc resource Not Found - Not deleted
            pass

        self.api.create_namespaced_custom_object(
                group="tekton.dev",
                version="v1alpha1",
                namespace=self.namespace,
                plural="pipelineresources",
                body=git_res
            )

        self.api.create_namespaced_custom_object(
                group="tekton.dev",
                version="v1alpha1",
                namespace=self.namespace,
                plural="tasks",
                body=task_def
            )

    def _build_default_runtime_from_git(self, docker_image_name):
        """
        Builds the default runtime and pushes it to the docker container registry
        """
        image_name, revision = docker_image_name.split(':')

        if self.knative_config['docker_repo'] == 'docker.io' and revision != 'latest':
            resp = requests.get('https://index.docker.io/v1/repositories/{}/tags/{}'
                                .format(docker_image_name, revision))
            if resp.status_code == 200:
                logger.debug('Docker image docker.io/{}:{} already exists in Dockerhub. '
                             'Skipping build process.'.format(docker_image_name, revision))
                return

        logger.debug("Building default Lithops runtime from git with Tekton")

        if not {"docker_user", "docker_token"} <= set(self.knative_config):
            raise Exception("You must provide 'docker_user' and 'docker_token'"
                            " to build the default runtime")

        task_run = yaml.safe_load(kconfig.task_run)
        task_run['spec']['inputs']['params'] = []
        python_version = version_str(sys.version_info).replace('.', '')
        path_to_dockerfile = {'name': 'pathToDockerFile',
                              'value': 'lithops/compute/backends/knative/tekton/Dockerfile.python{}'.format(python_version)}
        task_run['spec']['inputs']['params'].append(path_to_dockerfile)
        image_url = {'name': 'imageUrl',
                     'value': '/'.join([self.knative_config['docker_repo'], image_name])}
        task_run['spec']['inputs']['params'].append(image_url)
        image_tag = {'name': 'imageTag',
                     'value':  revision}
        task_run['spec']['inputs']['params'].append(image_tag)

        self._create_account_resources()
        self._create_build_resources()

        task_run_name = task_run['metadata']['name']
        try:
            self.api.delete_namespaced_custom_object(
                    group="tekton.dev",
                    version="v1alpha1",
                    name=task_run_name,
                    namespace=self.namespace,
                    plural="taskruns",
                    body=client.V1DeleteOptions()
                )
        except Exception:
            pass

        self.api.create_namespaced_custom_object(
                    group="tekton.dev",
                    version="v1alpha1",
                    namespace=self.namespace,
                    plural="taskruns",
                    body=task_run
                )

        logger.debug("Building runtime...")
        pod_name = None
        w = watch.Watch()
        for event in w.stream(self.api.list_namespaced_custom_object, namespace=self.namespace,
                              group="tekton.dev", version="v1alpha1", plural="taskruns",
                              field_selector="metadata.name={0}".format(task_run_name)):
            if event['object'].get('status'):
                pod_name = event['object']['status']['podName']
                w.stop()

        if pod_name is None:
            raise Exception('Unable to get the pod name from the task that is building the runtime')

        w = watch.Watch()
        for event in w.stream(self.v1.list_namespaced_pod, namespace=self.namespace,
                              field_selector="metadata.name={0}".format(pod_name)):
            if event['object'].status.phase == "Succeeded":
                w.stop()
            if event['object'].status.phase == "Failed":
                w.stop()
                logger.debug('Something went wrong building the default Lithops runtime with Tekton')
                for container in event['object'].status.container_statuses:
                    if container.state.terminated.reason == 'Error':
                        logs = self.v1.read_namespaced_pod_log(name=pod_name,
                                                               container=container.name,
                                                               namespace=self.namespace)
                        logger.debug("Tekton container '{}' failed: {}".format(container.name, logs.strip()))

                raise Exception('Unable to build the default Lithops runtime with Tekton')

        self.api.delete_namespaced_custom_object(
                    group="tekton.dev",
                    version="v1alpha1",
                    name=task_run_name,
                    namespace=self.namespace,
                    plural="taskruns",
                    body=client.V1DeleteOptions()
                )

        logger.debug('Default Lithops runtime built from git and uploaded to Dockerhub')

    def _build_default_runtime(self, default_runtime_img_name):
        """
        Builds the default runtime
        """
        if os.system('docker --version >{} 2>&1'.format(os.devnull)) == 0:
            # Build default runtime using local dokcer
            python_version = version_str(sys.version_info).replace('.', '')
            location = 'https://raw.githubusercontent.com/lithops-cloud/lithops/master/runtime/knative'
            resp = requests.get('{}/Dockerfile.python{}'.format(location, python_version))
            dockerfile = "Dockefile.default-kantive-runtime"
            if resp.status_code == 200:
                with open(dockerfile, 'w') as f:
                    f.write(resp.text)
                self.build_runtime(default_runtime_img_name, dockerfile)
                os.remove(dockerfile)
            else:
                msg = 'There was an error fetching the default runitme Dockerfile: {}'.format(resp.text)
                logger.error(msg)
                exit()
        else:
            # Build default runtime using Tekton
            self._build_default_runtime_from_git(default_runtime_img_name)

    def _create_service(self, docker_image_name, runtime_memory, timeout):
        """
        Creates a service in knative based on the docker_image_name and the memory provided
        """
        logger.debug("Creating Lithops runtime service in Knative")
        svc_res = yaml.safe_load(kconfig.service_res)

        service_name = self._format_service_name(docker_image_name, runtime_memory)
        svc_res['metadata']['name'] = service_name
        svc_res['metadata']['namespace'] = self.namespace

        logger.debug("Service name: {}".format(service_name))
        logger.debug("Namespace: {}".format(self.namespace))

        svc_res['spec']['template']['spec']['timeoutSeconds'] = timeout
        full_docker_image_name = '/'.join([self.knative_config['docker_repo'], docker_image_name])
        svc_res['spec']['template']['spec']['containers'][0]['image'] = full_docker_image_name
        svc_res['spec']['template']['spec']['containers'][0]['resources']['limits']['memory'] = '{}Mi'.format(runtime_memory)
        svc_res['spec']['template']['spec']['containers'][0]['resources']['limits']['cpu'] = '{}m'.format(self.knative_config['cpu'])

        try:
            # delete the service resource if exists
            self.api.delete_namespaced_custom_object(
                    group="serving.knative.dev",
                    version="v1alpha1",
                    name=service_name,
                    namespace=self.namespace,
                    plural="services",
                    body=client.V1DeleteOptions()
                )
            time.sleep(2)
        except Exception:
            pass

        # create the service resource
        self.api.create_namespaced_custom_object(
                group="serving.knative.dev",
                version="v1alpha1",
                namespace=self.namespace,
                plural="services",
                body=svc_res
            )

        w = watch.Watch()
        for event in w.stream(self.api.list_namespaced_custom_object,
                              namespace=self.namespace, group="serving.knative.dev",
                              version="v1alpha1", plural="services",
                              field_selector="metadata.name={0}".format(service_name),
                              timeout_seconds=300):
            if event['object'].get('status'):
                service_url = event['object']['status'].get('url')
                conditions = event['object']['status']['conditions']
                if conditions[0]['status'] == 'True' and \
                   conditions[1]['status'] == 'True' and \
                   conditions[2]['status'] == 'True':
                    w.stop()
                    time.sleep(2)

        log_msg = 'Runtime Service created - URL: {}'.format(service_url)
        logger.debug(log_msg)

        self.service_host_suffix = service_url[7:].replace(service_name, '')
        # Store service host suffix in local cache
        serice_host_data = {}
        serice_host_data['service_host_suffix'] = self.service_host_suffix
        dump_yaml_config(self.serice_host_filename, serice_host_data)
        self.knative_config['service_host_suffix'] = self.service_host_suffix

        return service_url

    def _generate_runtime_meta(self, docker_image_name, memory):
        """
        Extract installed Python modules from docker image
        """
        payload = {}

        payload['service_route'] = "/preinstalls"
        logger.debug("Extracting Python modules list from: {}".format(docker_image_name))
        try:
            runtime_meta = self.invoke(docker_image_name, memory, payload, return_result=True)
        except Exception as e:
            raise Exception("Unable to extract the preinstalled modules from the runtime: {}".format(e))

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception('Failed getting runtime metadata: {}'.format(runtime_meta))

        return runtime_meta

    def create_runtime(self, docker_image_name, memory, timeout=kconfig.RUNTIME_TIMEOUT_DEFAULT):
        """
        Creates a new runtime into the knative default namespace from an already built Docker image.
        As knative does not have a default image already published in a docker registry, lithops
        has to build it in the docker hub account provided by the user. So when the runtime docker
        image name is not provided by the user in the config, lithops will build the default from git.
        """
        default_runtime_img_name = self._get_default_runtime_image_name()
        if docker_image_name in ['default', default_runtime_img_name]:
            # We only build the default image. rest of images must already exist
            # in the docker registry.
            docker_image_name = default_runtime_img_name
            self._build_default_runtime(default_runtime_img_name)

        self._create_service(docker_image_name, memory, timeout)
        runtime_meta = self._generate_runtime_meta(docker_image_name, memory)

        return runtime_meta

    def _delete_function_handler_zip(self):
        os.remove(kconfig.FH_ZIP_LOCATION)

    def build_runtime(self, docker_image_name, dockerfile):
        """
        Builds a new runtime from a Docker file and pushes it to the Docker hub
        """
        logger.info('Building a new docker image from Dockerfile')
        logger.info('Docker image name: {}'.format(docker_image_name))

        expression = '^([a-z0-9]+)/([-a-z0-9]+)(:[a-z0-9]+)?'
        result = re.match(expression, docker_image_name)

        if not result or result.group() != docker_image_name:
            raise Exception("Invalid docker image name: '.' or '_' characters are not allowed")

        create_function_handler_zip(kconfig.FH_ZIP_LOCATION, 'lithopsproxy.py', __file__)

        if dockerfile:
            cmd = 'docker build -t {} -f {} .'.format(docker_image_name, dockerfile)
        else:
            cmd = 'docker build -t {} .'.format(docker_image_name)

        if not self.log_active:
            cmd = cmd + " >{} 2>&1".format(os.devnull)

        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error building the runtime')

        self._delete_function_handler_zip()

        cmd = 'docker push {}'.format(docker_image_name)
        if not self.log_active:
            cmd = cmd + " >{} 2>&1".format(os.devnull)
        res = os.system(cmd)
        if res != 0:
            raise Exception('There was an error pushing the runtime to the container registry')

    def delete_runtime(self, docker_image_name, memory):
        service_name = self._format_service_name(docker_image_name, memory)
        logger.info('Deleting runtime: {}'.format(service_name))
        try:
            self.api.delete_namespaced_custom_object(
                    group="serving.knative.dev",
                    version="v1alpha1",
                    name=service_name,
                    namespace=self.namespace,
                    plural="services",
                    body=client.V1DeleteOptions()
                )
        except Exception:
            pass

    def delete_all_runtimes(self):
        """
        Deletes all runtimes deployed in knative
        """
        runtimes = self.list_runtimes()
        for docker_image_name, memory in runtimes:
            self.delete_runtime(docker_image_name, memory)

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes deployed in knative
        return: list of tuples [docker_image_name, memory]
        """
        knative_services = self.api.list_namespaced_custom_object(
                                group="serving.knative.dev",
                                version="v1alpha1",
                                namespace=self.namespace,
                                plural="services"
                            )
        runtimes = []

        for service in knative_services['items']:
            try:
                if service['spec']['template']['metadata']['labels']['type'] == 'lithops-runtime':
                    runtime_name = service['metadata']['name']
                    image_name, memory = self._unformat_service_name(runtime_name)
                    if docker_image_name == image_name or docker_image_name == 'all':
                        runtimes.append((image_name, memory))
            except Exception:
                # It is not a lithops runtime
                pass

        return runtimes

    def invoke(self, docker_image_name, memory, payload, return_result=False):
        """
        Invoke -- return information about this invocation
        """
        service_name = self._format_service_name(docker_image_name, memory)
        if self.service_host_suffix:
            service_host = service_name+self.service_host_suffix
        else:
            service_host = self._get_service_host(service_name)

        headers = {}

        if self.istio_endpoint:
            headers['Host'] = service_host
            endpoint = self.istio_endpoint
        else:
            endpoint = 'http://{}'.format(service_host)

        exec_id = payload.get('executor_id')
        call_id = payload.get('call_id')
        job_id = payload.get('job_id')
        route = payload.get("service_route", '/')

        try:
            parsed_url = urlparse(endpoint)

            if endpoint.startswith('https'):
                ctx = ssl._create_unverified_context()
                conn = http.client.HTTPSConnection(parsed_url.netloc, context=ctx)
            else:
                conn = http.client.HTTPConnection(parsed_url.netloc)

            conn.request("POST", route, body=json.dumps(payload), headers=headers)

            if exec_id and job_id and call_id:
                logger.debug('ExecutorID {} | JobID {} - Function call {} invoked'
                             .format(exec_id, job_id, call_id))
            elif exec_id and job_id:
                logger.debug('ExecutorID {} | JobID {} - Function invoked'
                             .format(exec_id, job_id))
            else:
                logger.debug('Function invoked')

            resp = conn.getresponse()
            resp_status = resp.status
            resp_data = resp.read().decode("utf-8")
            conn.close()
        except Exception as e:
            raise e

        if resp_status in [200, 202]:
            data = json.loads(resp_data)
            if return_result:
                return data
            return data["activationId"]
        elif resp_status == 404:
            raise Exception("Lithops runtime is not deployed in your k8s cluster")
        else:
            logger.debug('ExecutorID {} | JobID {} - Function call {} failed ({}). Retrying request'
                         .format(exec_id, job_id, call_id, resp_data.replace('.', '')))

    def get_runtime_key(self, docker_image_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        service_name = self._format_service_name(docker_image_name, runtime_memory)
        runtime_key = os.path.join(self.cluster, self.namespace, service_name)

        return runtime_key
