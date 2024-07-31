#
# (C) Copyright Cloudlab URV 2021
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
import pika
import base64
import hashlib
import json
import logging
import copy
import time
import yaml
import urllib3
from kubernetes import client, watch
from kubernetes.config import load_kube_config, \
    load_incluster_config, list_kube_config_contexts, \
    KUBE_CONFIG_DEFAULT_LOCATION
from kubernetes.client.rest import ApiException

from lithops import utils
from lithops.version import __version__
from lithops.constants import COMPUTE_CLI_MSG, JOBS_PREFIX

from . import config


logger = logging.getLogger(__name__)
urllib3.disable_warnings()


class KubernetesBackend:
    """
    A wrap-up around Kubernetes backend.
    """

    def __init__(self, k8s_config, internal_storage):
        logger.debug("Creating Kubernetes client")
        self.name = 'k8s'
        self.type = utils.BackendType.BATCH.value
        self.k8s_config = k8s_config
        self.internal_storage = internal_storage

        self.kubecfg_path = k8s_config.get('kubecfg_path', os.environ.get("KUBECONFIG"))
        self.kubecfg_path = os.path.expanduser(self.kubecfg_path or KUBE_CONFIG_DEFAULT_LOCATION)
        self.kubecfg_context = k8s_config.get('kubecfg_context', 'default')
        self.namespace = k8s_config.get('namespace', 'default')
        self.cluster = k8s_config.get('cluster', 'default')
        self.user = k8s_config.get('user', 'default')
        self.master_name = k8s_config.get('master_name', config.MASTER_NAME)
        self.rabbitmq_executor = self.k8s_config.get('rabbitmq_executor', False)

        if os.path.exists(self.kubecfg_path):
            logger.debug(f"Loading kubeconfig file: {self.kubecfg_path}")
            context = None if self.kubecfg_context == 'default' else self.kubecfg_context
            load_kube_config(config_file=self.kubecfg_path, context=context)
            contexts, current_context = list_kube_config_contexts(config_file=self.kubecfg_path)
            current_context = current_context if context is None else [it for it in contexts if it['name'] == context][0]
            ctx_name = current_context.get('name')
            ctx_context = current_context.get('context')
            self.namespace = ctx_context.get('namespace') or self.namespace
            self.cluster = ctx_context.get('cluster') or self.cluster
            ctx_user = ctx_context.get('user')
            self.user = hashlib.sha1(ctx_user.encode()).hexdigest()[:10] if ctx_user else self.user
            logger.debug(f"Using kubeconfig conetxt: {ctx_name} - cluster: {self.cluster}")
            self.is_incluster = False
        else:
            logger.debug('kubeconfig file not found, loading incluster config')
            load_incluster_config()
            self.is_incluster = True

        if self.master_name == config.MASTER_NAME:
            self.master_name = f'{config.MASTER_NAME}-{self.user}'

        self.k8s_config['namespace'] = self.namespace
        self.k8s_config['cluster'] = self.cluster
        self.k8s_config['user'] = self.user
        self.k8s_config['master_name'] = self.master_name

        self.batch_api = client.BatchV1Api()
        self.core_api = client.CoreV1Api()

        if self.rabbitmq_executor:
            self.amqp_url = self.k8s_config['amqp_url']

            # Init rabbitmq
            params = pika.URLParameters(self.amqp_url)
            self.connection = pika.BlockingConnection(params)
            self.channel = self.connection.channel()

            # Define some needed variables
            self._get_nodes()
            self.image = ""

        self.jobs = []  # list to store executed jobs (job_keys)

        msg = COMPUTE_CLI_MSG.format('Kubernetes')
        logger.info(f"{msg} - Namespace: {self.namespace}")

    def _format_job_name(self, runtime_name, runtime_memory, version=__version__):
        name = f'{runtime_name}-{runtime_memory}-{version}-{self.user}'
        name_hash = hashlib.sha1(name.encode()).hexdigest()[:10]

        return f'lithops-worker-{version.replace(".", "")}-{name_hash}'

    def _get_default_runtime_image_name(self):
        """
        Generates the default runtime image name
        """
        return utils.get_default_container_name(
            self.name, self.k8s_config, 'lithops-kubernetes-default'
        )

    def build_runtime(self, docker_image_name, dockerfile, extra_args=[]):
        """
        Builds a new runtime from a Docker file and pushes it to the registry
        """
        logger.info(f'Building runtime {docker_image_name} from {dockerfile or "Dockerfile"}')

        docker_path = utils.get_docker_path()

        if dockerfile:
            assert os.path.isfile(dockerfile), f'Cannot locate "{dockerfile}"'
            cmd = f'{docker_path} build --platform=linux/amd64 -t {docker_image_name} -f {dockerfile} . '
        else:
            cmd = f'{docker_path} build --platform=linux/amd64 -t {docker_image_name} . '
        cmd = cmd + ' '.join(extra_args)

        try:
            entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
            utils.create_handler_zip(config.FH_ZIP_LOCATION, entry_point, 'lithopsentry.py')
            utils.run_command(cmd)
        finally:
            os.remove(config.FH_ZIP_LOCATION)

        docker_user = self.k8s_config.get("docker_user")
        docker_password = self.k8s_config.get("docker_password")
        docker_server = self.k8s_config.get("docker_server")

        if docker_user and docker_password:
            logger.debug('Container registry credentials found in config. Logging in into the registry')
            cmd = f'{docker_path} login -u {docker_user} --password-stdin {docker_server}'
            utils.run_command(cmd, input=docker_password)

        logger.debug(f'Pushing runtime {docker_image_name} to container registry')
        if utils.is_podman(docker_path):
            cmd = f'{docker_path} push {docker_image_name} --format docker --remove-signatures'
        else:
            cmd = f'{docker_path} push {docker_image_name}'
        utils.run_command(cmd)

        logger.debug('Building done!')

    def _build_default_runtime(self, docker_image_name):
        """
        Builds the default runtime
        """
        # Build default runtime using local dokcer
        dockerfile = "Dockefile.default-k8s-runtime"
        with open(dockerfile, 'w') as f:
            f.write(f"FROM python:{utils.CURRENT_PY_VERSION}-slim-buster\n")
            f.write(config.DOCKERFILE_DEFAULT)
        try:
            self.build_runtime(docker_image_name, dockerfile)
        finally:
            os.remove(dockerfile)

    def _create_container_registry_secret(self):
        """
        Create the container registry secret in the cluster
        (only if credentials are present in config)
        """
        if not all(key in self.k8s_config for key in ["docker_user", "docker_password"]):
            return

        logger.debug('Creating container registry secret')
        docker_server = self.k8s_config['docker_server']
        docker_user = self.k8s_config['docker_user']
        docker_password = self.k8s_config['docker_password']

        cred_payload = {
            "auths": {
                docker_server: {
                    "Username": docker_user,
                    "Password": docker_password
                }
            }
        }

        data = {
            ".dockerconfigjson": base64.b64encode(
                json.dumps(cred_payload).encode()
            ).decode()
        }

        secret = client.V1Secret(
            api_version="v1",
            data=data,
            kind="Secret",
            metadata=dict(name="lithops-regcred", namespace=self.namespace),
            type="kubernetes.io/dockerconfigjson",
        )

        try:
            self.core_api.delete_namespaced_secret("lithops-regcred", self.namespace)
        except ApiException:
            pass

        try:
            self.core_api.create_namespaced_secret(self.namespace, secret)
        except ApiException as e:
            if e.status != 409:
                raise e

    def deploy_runtime(self, docker_image_name, memory, timeout):
        """
        Deploys a new runtime
        """
        try:
            default_image_name = self._get_default_runtime_image_name()
        except Exception:
            default_image_name = None
        if docker_image_name == default_image_name:
            self._build_default_runtime(docker_image_name)

        logger.info(f"Deploying runtime: {docker_image_name} - Memory: {memory} Timeout: {timeout}")
        self._create_container_registry_secret()
        runtime_meta = self._generate_runtime_meta(docker_image_name)

        return runtime_meta

    def delete_runtime(self, docker_image_name, memory, version=__version__):
        """
        Deletes a runtime
        """
        pass

    def clean(self, all=False):
        """
        Deletes all jobs
        """
        logger.debug('Cleaning lithops resources in kubernetes')

        try:
            self._delete_workers()
            jobs = self.batch_api.list_namespaced_job(
                namespace=self.namespace,
                label_selector=f'user={self.user}'
            )
            for job in jobs.items:
                if job.metadata.labels['type'] == 'lithops-worker'\
                   and (job.status.completion_time is not None or all):
                    job_name = job.metadata.name
                    logger.debug(f'Deleting job {job_name}')
                    try:
                        self.batch_api.delete_namespaced_job(
                            name=job_name,
                            namespace=self.namespace,
                            propagation_policy='Background'
                        )
                    except ApiException:
                        pass
        except ApiException:
            pass

    def clear(self, job_keys=None):
        """
        Delete only completed jobs
        """
        jobs_to_delete = job_keys or self.jobs

        for job_key in jobs_to_delete:
            job_name = f'lithops-{job_key.lower()}'
            logger.debug(f'Deleting job {job_name}')
            try:
                self.batch_api.delete_namespaced_job(
                    name=job_name,
                    namespace=self.namespace,
                    propagation_policy='Background'
                )
            except ApiException:
                pass
            try:
                self.jobs.remove(job_key)
            except ValueError:
                pass

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes
        return: list of tuples (docker_image_name, memory)
        """
        logger.debug('Listing runtimes')
        logger.debug('Note that this backend does not manage runtimes')
        return []

    def _create_pod(self, pod, pod_name, cpu, memory):
        pod["metadata"]["name"] = f"lithops-pod-{pod_name}"
        node_name = re.sub(r'-\d+$', '', pod_name)
        pod["spec"]["nodeName"] = node_name
        pod["spec"]["containers"][0]["image"] = self.image
        pod["spec"]["containers"][0]["resources"]["requests"]["cpu"] = str(cpu)
        pod["spec"]["containers"][0]["resources"]["requests"]["memory"] = memory
        pod["metadata"]["labels"] = {"app": "lithops-pod"}

        payload = {
            'log_level': 'DEBUG',
            'amqp_url': self.amqp_url,
            'cpus_pod': cpu,
        }

        pod["spec"]["containers"][0]["args"][1] = "start_rabbitmq"
        pod["spec"]["containers"][0]["args"][2] = utils.dict_to_b64str(payload)

        self.core_api.create_namespaced_pod(body=pod, namespace=self.namespace)

    def _get_nodes(self):
        self.nodes = []
        list_all_nodes = self.core_api.list_node()
        for node in list_all_nodes.items:
            # If the node is tainted, skip it
            if node.spec.taints:
                continue

            # Check if the CPU is in millicores
            if isinstance(node.status.allocatable['cpu'], str) and 'm' in node.status.allocatable['cpu']:
                # Extract the number part and convert it to an integer
                number_match = re.search(r'\d+', node.status.allocatable['cpu'])
                if number_match:
                    number = int(number_match.group())

                    # Round to the nearest whole number of CPUs - 1
                    cpu_info = round(number / 1000) - 1

                    if cpu_info < 1:
                        cpu_info = 0
                else:
                    # Handle the case where the CPU is in millicores but no number is found
                    cpu_info = 0
            else:
                # CPU is not in millicores
                cpu_info = node.status.allocatable['cpu']

            self.nodes.append({
                "name": node.metadata.name,
                "cpu": cpu_info,
                "memory": node.status.allocatable['memory']
            })

    def _create_workers(self, runtime_memory):
        default_pod_config = yaml.load(config.POD, Loader=yaml.loader.SafeLoader)
        granularity = self.k8s_config['worker_processes']
        cluster_info_cpu = {}
        cluster_info_mem = {}
        num_cpus_cluster = 0

        # If the unit is not specified, assume it is in MB
        try:
            mem_num, mem_uni = re.match(r'(\d+)(\D*)', runtime_memory).groups()
        except TypeError:
            mem_num = runtime_memory
            mem_uni = 'M'

        if granularity <= 1:
            granularity = False

        for node in self.nodes:
            cpus_node = int(float(node["cpu"]) * 0.9)

            if granularity:
                times, res = divmod(cpus_node, granularity)

                for i in range(times):
                    cluster_info_cpu[f"{node['name']}-{i}"] = granularity
                    cluster_info_mem[f"{node['name']}-{i}"] = f"{mem_num}{mem_uni}"
                    num_cpus_cluster += granularity
                if res != 0:
                    cluster_info_cpu[f"{node['name']}-{times}"] = res
                    cluster_info_mem[f"{node['name']}-{times}"] = f"{mem_num}{mem_uni}"
                    num_cpus_cluster += res
            else:
                cluster_info_cpu[node["name"] + "-0"] = cpus_node
                num_cpus_cluster += cpus_node

                # If runtime_memory is not defined in the config, use 80% of the node memory
                if runtime_memory == 512:
                    mem_num, mem_uni = re.match(r'(\d+)(\D*)', node["memory"]).groups()
                    mem_num = int(float(mem_num) * 0.8)
                    cluster_info_mem[node["name"] + "-0"] = f"{mem_num}{mem_uni}"
                else:
                    cluster_info_mem[node["name"] + "-0"] = f"{mem_num}{mem_uni}"

        if num_cpus_cluster == 0:
            raise ValueError("Total CPUs of the cluster cannot be 0")

        # Create all the pods
        for pod_name in cluster_info_cpu.keys():
            self._create_pod(default_pod_config, pod_name, cluster_info_cpu[pod_name], cluster_info_mem[pod_name])

        logger.info(f"Total cpus of the cluster: {num_cpus_cluster}")

    def _delete_workers(self):
        list_pods = self.core_api.list_namespaced_pod(self.namespace, label_selector="app=lithops-pod")
        for pod in list_pods.items:
            self.core_api.delete_namespaced_pod(pod.metadata.name, self.namespace)

        # Wait until all pods are deleted
        while True:
            list_pods = self.core_api.list_namespaced_pod(self.namespace, label_selector="app=lithops-pod")

            if not list_pods.items:
                break  # All pods are deleted

        logger.info('All pods are deleted.')

    def _start_master(self, docker_image_name):

        master_pod = self.core_api.list_namespaced_pod(
            namespace=self.namespace,
            label_selector=f"job-name={self.master_name}"
        )

        if len(master_pod.items) > 0:
            return master_pod.items[0].status.pod_ip

        logger.debug('Starting Lithops master Pod')
        try:
            self.batch_api.delete_namespaced_job(
                name=self.master_name,
                namespace=self.namespace,
                propagation_policy='Background'
            )
            time.sleep(2)
        except ApiException:
            pass

        master_res = yaml.safe_load(config.JOB_DEFAULT)
        master_res['metadata']['name'] = self.master_name
        master_res['metadata']['namespace'] = self.namespace
        master_res['metadata']['labels']['version'] = 'lithops_v' + __version__
        master_res['metadata']['labels']['user'] = self.user
        master_res['spec']['activeDeadlineSeconds'] = self.k8s_config['master_timeout']

        container = master_res['spec']['template']['spec']['containers'][0]
        container['image'] = docker_image_name
        container['env'][0]['value'] = 'run_master'

        payload = {'log_level': 'DEBUG'}
        container['env'][1]['value'] = utils.dict_to_b64str(payload)

        if not all(key in self.k8s_config for key in ["docker_user", "docker_password"]):
            del master_res['spec']['template']['spec']['imagePullSecrets']

        try:
            self.batch_api.create_namespaced_job(
                namespace=self.namespace,
                body=master_res
            )
        except ApiException as e:
            raise e

        logger.debug('Waiting Lithops master pod to be ready')
        w = watch.Watch()
        for event in w.stream(self.core_api.list_namespaced_pod,
                              namespace=self.namespace,
                              label_selector=f"job-name={self.master_name}"):
            if event['object'].status.phase == "Running":
                w.stop()
                return event['object'].status.pod_ip

    def convert_memory_units(self, mem_num, mem_uni):
        mem_num = int(mem_num)

        if 'i' in mem_uni:
            mem_num *= 1024
            mem_uni = mem_uni[:-1]
        if 'K' in mem_uni:
            mem_num = mem_num / (1024 if 'i' in mem_uni else 1000)
        elif 'G' in mem_uni:
            mem_num = mem_num * (1024 if 'i' in mem_uni else 1000)

        return mem_num, 'M'

    # Detect if granularity, memory or runtime image changed or not
    def _has_config_changed(self, runtime_mem):
        config_granularity = False if self.k8s_config['worker_processes'] <= 1 else self.k8s_config['worker_processes']
        config_memory = self.k8s_config['runtime_memory'] if self.k8s_config['runtime_memory'] != 512 else False

        self.current_runtime = ""

        list_pods = self.core_api.list_namespaced_pod(self.namespace, label_selector="app=lithops-pod")

        for pod in list_pods.items:
            pod_name = pod.metadata.name

            # Get the node info where the pod is running
            node_info = next((node for node in self.nodes if node["name"] == pod.spec.node_name), False)
            if not node_info:
                return True

            # Get the pod info
            self.current_runtime = pod.spec.containers[0].image
            pod_resource_cpu = int(pod.spec.containers[0].resources.requests.get('cpu', '0m'))
            pod_resource_memory = pod.spec.containers[0].resources.requests.get('memory', '0Mi')

            multiples_pods_per_node = re.search(r'-\d+(?<!-0)$', pod_name)

            node_cpu = int(float(node_info["cpu"]) * 0.9)
            node_mem_num, node_mem_uni = re.match(r'(\d+)(\D*)', node_info["memory"]).groups()
            pod_mem_num, pod_mem_uni = re.match(r'(\d+)(\D*)', pod_resource_memory).groups()

            node_mem_num = int(float(node_mem_num) * 0.8)

            # Match the same unit of runtime memory and pod memory
            try:
                config_mem_num, config_mem_uni = re.match(r'(\d+)(\D*)', config_memory).groups()
                config_mem_num, config_mem_uni = self.convert_memory_units(config_mem_num, config_mem_uni)
            except TypeError:
                config_mem_num = config_memory
                config_mem_uni = 'M'

            pod_mem_num, pod_mem_uni = self.convert_memory_units(pod_mem_num, pod_mem_uni)
            node_mem_num, node_mem_uni = self.convert_memory_units(node_mem_num, node_mem_uni)

            # There are pods with cpu granularity
            if multiples_pods_per_node:
                # Is lithops pod with granularity and the user doesn't want it
                if not config_granularity:
                    return True
                # There is granularity but the pod doesn't have the default memory
                if not config_memory and pod_mem_num != runtime_mem:
                    return True
                # There is granularity but the pod doesn't have the desired memory
                if config_memory and pod_mem_num != config_mem_num:
                    return True
            else:
                # There is a custom memory but the pod doesn't have the desired memory
                if config_memory:
                    if pod_mem_num != config_mem_num:
                        return True
                # The pod has custom_memory and the user doesn't want it
                else:
                    if pod_mem_num != node_mem_num and pod_mem_num != runtime_mem:
                        return True

            # The cpu granularity changed
            if config_granularity:
                node_granularity_cpu = node_cpu % config_granularity
                if pod_resource_cpu != config_granularity and pod_resource_cpu != node_granularity_cpu:
                    return True

        # The runtime image changed
        if self.current_runtime and self.current_runtime != self.image:
            return True

        return False

    def invoke(self, docker_image_name, runtime_memory, job_payload):
        """
        Invoke -- return information about this invocation
        For array jobs only remote_invocator is allowed
        """
        if self.rabbitmq_executor:
            self.image = docker_image_name
            config_changed = self._has_config_changed(runtime_memory)

            if config_changed:
                logger.debug("Waiting for kubernetes to change the configuration")
                self._delete_workers()
                self._create_workers(runtime_memory)

            # First init
            elif self.current_runtime != self.image:
                self._create_workers(runtime_memory)

            job_key = job_payload['job_key']
            self.jobs.append(job_key)

            # Send packages of tasks to the queue
            granularity = max(1, job_payload['total_calls'] // len(self.nodes)
                              if self.k8s_config['worker_processes'] <= 1 else self.k8s_config['worker_processes'])

            times, res = divmod(job_payload['total_calls'], granularity)

            for i in range(times + (1 if res != 0 else 0)):
                num_tasks = granularity if i < times else res
                payload_edited = job_payload.copy()

                start_index = i * granularity
                end_index = start_index + num_tasks

                payload_edited['call_ids'] = payload_edited['call_ids'][start_index:end_index]
                payload_edited['data_byte_ranges'] = payload_edited['data_byte_ranges'][start_index:end_index]
                payload_edited['total_calls'] = num_tasks

                self.channel.basic_publish(
                    exchange='',
                    routing_key='task_queue',
                    body=json.dumps(payload_edited),
                    properties=pika.BasicProperties(
                        delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE
                    ))

            activation_id = f'lithops-{job_key.lower()}'
        else:
            master_ip = self._start_master(docker_image_name)

            max_workers = job_payload['max_workers']
            executor_id = job_payload['executor_id']
            job_id = job_payload['job_id']

            job_key = job_payload['job_key']
            self.jobs.append(job_key)

            total_calls = job_payload['total_calls']
            chunksize = job_payload['chunksize']
            total_workers = min(max_workers, total_calls // chunksize + (total_calls % chunksize > 0))

            logger.debug(
                f'ExecutorID {executor_id} | JobID {job_id} - Required Workers: {total_workers}'
            )

            activation_id = f'lithops-{job_key.lower()}'

            job_res = yaml.safe_load(config.JOB_DEFAULT)
            job_res['metadata']['name'] = activation_id
            job_res['metadata']['namespace'] = self.namespace
            job_res['metadata']['labels']['version'] = 'lithops_v' + __version__
            job_res['metadata']['labels']['user'] = self.user

            job_res['spec']['activeDeadlineSeconds'] = self.k8s_config['runtime_timeout']
            job_res['spec']['parallelism'] = total_workers

            container = job_res['spec']['template']['spec']['containers'][0]
            container['image'] = docker_image_name
            if not docker_image_name.endswith(':latest'):
                container['imagePullPolicy'] = 'IfNotPresent'

            container['env'][0]['value'] = 'run_job'
            container['env'][1]['value'] = utils.dict_to_b64str(job_payload)
            container['env'][2]['value'] = master_ip

            container['resources']['requests']['memory'] = f'{runtime_memory}Mi'
            container['resources']['requests']['cpu'] = str(self.k8s_config['runtime_cpu'])
            container['resources']['limits']['memory'] = f'{runtime_memory}Mi'
            container['resources']['limits']['cpu'] = str(self.k8s_config['runtime_cpu'])

            logger.debug(f'ExecutorID {executor_id} | JobID {job_id} - Going '
                         f'to run {total_calls} activations in {total_workers} workers')

            if not all(key in self.k8s_config for key in ["docker_user", "docker_password"]):
                del job_res['spec']['template']['spec']['imagePullSecrets']

            try:
                self.batch_api.create_namespaced_job(
                    namespace=self.namespace,
                    body=job_res
                )
            except ApiException as e:
                raise e

        return activation_id

    def _generate_runtime_meta(self, docker_image_name):
        runtime_name = self._format_job_name(docker_image_name, 128)
        meta_job_name = f'{runtime_name}-meta'

        logger.info(f"Extracting metadata from: {docker_image_name}")

        payload = copy.deepcopy(self.internal_storage.storage.config)
        payload['runtime_name'] = runtime_name
        payload['log_level'] = logger.getEffectiveLevel()

        job_res = yaml.safe_load(config.JOB_DEFAULT)
        job_res['metadata']['name'] = meta_job_name
        job_res['metadata']['namespace'] = self.namespace
        job_res['metadata']['labels']['version'] = 'lithops_v' + __version__
        job_res['metadata']['labels']['user'] = self.user

        container = job_res['spec']['template']['spec']['containers'][0]
        container['image'] = docker_image_name
        container['imagePullPolicy'] = 'Always'
        container['env'][0]['value'] = 'get_metadata'
        container['env'][1]['value'] = utils.dict_to_b64str(payload)

        if not all(key in self.k8s_config for key in ["docker_user", "docker_password"]):
            del job_res['spec']['template']['spec']['imagePullSecrets']

        try:
            self.batch_api.delete_namespaced_job(
                namespace=self.namespace,
                name=meta_job_name,
                propagation_policy='Background'
            )
        except ApiException:
            pass

        try:
            self.batch_api.create_namespaced_job(
                namespace=self.namespace,
                body=job_res
            )
        except ApiException as e:
            raise e

        logger.debug("Waiting for runtime metadata")

        done = failed = False
        w = watch.Watch()
        while not (done or failed):
            try:
                for event in w.stream(self.batch_api.list_namespaced_job,
                                      namespace=self.namespace,
                                      field_selector=f"metadata.name={meta_job_name}",
                                      timeout_seconds=10):
                    failed = event['object'].status.failed
                    done = event['object'].status.succeeded
                    logger.debug('...')
            except Exception:
                pass
        w.stop()

        if done:
            logger.debug("Runtime metadata generated successfully")

        try:
            self.batch_api.delete_namespaced_job(
                namespace=self.namespace,
                name=meta_job_name,
                propagation_policy='Background'
            )
        except ApiException:
            pass

        if failed:
            raise Exception("Unable to extract metadata from the runtime")

        data_key = '/'.join([JOBS_PREFIX, runtime_name + '.meta'])
        json_str = self.internal_storage.get_data(key=data_key)
        runtime_meta = json.loads(json_str.decode("ascii"))
        self.internal_storage.del_data(key=data_key)

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(f'Failed getting runtime metadata: {runtime_meta}')

        return runtime_meta

    def get_runtime_key(self, docker_image_name, runtime_memory, version=__version__):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        jobdef_name = self._format_job_name(docker_image_name, 256, version)
        user_data = os.path.join(self.cluster, self.namespace, self.user)
        runtime_key = os.path.join(self.name, version, user_data, jobdef_name)

        return runtime_key

    def get_runtime_info(self):
        """
        Method that returns all the relevant information about the runtime set
        in config
        """
        if 'runtime' not in self.k8s_config or self.k8s_config['runtime'] == 'default':
            self.k8s_config['runtime'] = self._get_default_runtime_image_name()

        runtime_info = {
            'runtime_name': self.k8s_config['runtime'],
            'runtime_cpu': self.k8s_config['runtime_cpu'],
            'runtime_memory': self.k8s_config['runtime_memory'],
            'runtime_timeout': self.k8s_config['runtime_timeout'],
            'max_workers': self.k8s_config['max_workers'],
        }

        return runtime_info
