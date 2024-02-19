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


class SingularityBackend:
    """
    A wrap-up around Singularity backend.
    """

    def __init__(self, singularity_config, internal_storage):
        logger.debug("Creating Singularity client")
        self.name = 'singularity'
        self.type = utils.BackendType.BATCH.value
        self.singularity_config = singularity_config
        self.internal_storage = internal_storage

        print("Singularity config: ", singularity_config)

        self.amqp_url = self.singularity_config.get('amqp_url', False)

        if not self.amqp_url:
            raise Exception('RabbitMQ executor is needed in this backend')

        # Init rabbitmq
        params = pika.URLParameters(self.amqp_url)
        self.connection = pika.BlockingConnection(params)
        self.channel = self.connection.channel()

        # Define some needed variables
        self.image = ""

        self.jobs = []  # list to store executed jobs (job_keys)

        msg = COMPUTE_CLI_MSG.format('Singularity')
        logger.info(f"{msg}")

    # TODO
    def _format_job_name(self, runtime_name, runtime_memory, version=__version__):
        name = f'{runtime_name}-{runtime_memory}-{version}'
        name_hash = hashlib.sha1(name.encode()).hexdigest()[:10]

        return f'lithops-worker-{version.replace(".", "")}-{name_hash}'

    # DONE
    def _get_default_runtime_image_name(self):
        """
        Generates the default runtime image name
        """
        py_version = utils.CURRENT_PY_VERSION.replace('.', '')
        return f'singularity-runtime-v{py_version}'

    # DONE
    def build_runtime(self, singularity_image_name, singularityfile, extra_args=[]):
        """
        Builds a new runtime from a Singularity file and pushes it to the registry
        """
        logger.info(f'Building runtime {singularity_image_name} from {singularityfile or "Singularity"}')

        singularity_path = utils.get_singularity_path()

        if singularityfile:
            assert os.path.isfile(singularityfile), f'Cannot locate "{singularityfile}"'
            cmd = f'{singularity_path} build  --fakeroot --force /tmp/{singularity_image_name}.sif {singularityfile} '
        else:
            default_singularityfile = self._create_default_runtime()
            cmd = f'{singularity_path} build --fakeroot --force /tmp/{singularity_image_name}.sif {default_singularityfile}'
        cmd = cmd + ' '.join(extra_args)

        try:
            entry_point = os.path.join(os.path.dirname(__file__), 'entry_point.py')
            utils.create_handler_zip(config.FH_ZIP_LOCATION, entry_point, 'lithopsentry.py')
            utils.run_command(cmd)
        finally:
            os.remove(config.FH_ZIP_LOCATION)

            if not singularityfile:
                os.remove(default_singularityfile)

        logger.debug('Building done!')

    # DONE
    def _create_default_runtime(self):
        """
        Builds the default runtime
        """
        # Build default runtime using local dokcer
        singularityfile = 'singularity_template'

        with open(singularityfile, 'w') as f:
            f.write(f"Bootstrap: docker\n")
            f.write(f"From: python:{utils.CURRENT_PY_VERSION}-slim-buster\n\n")
            f.write(config.SINGULARITYFILE_DEFAULT)

        return singularityfile

    # TODO
    def deploy_runtime(self, singularity_image_name):
        """
        Deploys a new runtime
        """
        try:
            default_image_name = self._get_default_runtime_image_name()
        except Exception:
            default_image_name = None
        
        if singularity_image_name == default_image_name:
            self.build_runtime(singularity_image_name, None)

        logger.info(f"Deploying runtime: {singularity_image_name}")
        runtime_meta = self._generate_runtime_meta(singularity_image_name)

        return runtime_meta

    # DONE
    def delete_runtime(self, singularity_image_name, memory, version):
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

    # DONE
    def list_runtimes(self, singularity_image_name='all'):
        """
        List all the runtimes
        return: list of tuples (docker_image_name, memory)
        """
        logger.debug('Listing runtimes')
        logger.debug('Note that this backend does not manage runtimes')
        return []

    def _create_pod(self, pod, pod_name, cpu, memory):
        pod["metadata"]["name"] = f"lithops-pod-{pod_name}"
        pod["spec"]["nodeName"] = pod_name.split("-")[0]
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
        granularity = self.singularity_config['worker_processes']
        cluster_info_cpu = {}
        cluster_info_mem = {}
        num_cpus_cluster = 0

        if granularity <= 1:
            granularity = False

        for node in self.nodes:
            cpus_node = int(float(node["cpu"]) * 0.9)

            if granularity:
                times, res = divmod(cpus_node, granularity)

                for i in range(times):
                    cluster_info_cpu[f"{node['name']}-{i}"] = granularity
                    cluster_info_mem[f"{node['name']}-{i}"] = runtime_memory
                    num_cpus_cluster += granularity
                if res != 0:
                    cluster_info_cpu[f"{node['name']}-{times}"] = res
                    cluster_info_mem[f"{node['name']}-{times}"] = runtime_memory
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
                    cluster_info_mem[node["name"] + "-0"] = str(runtime_memory)

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

        container = master_res['spec']['template']['spec']['containers'][0]
        container['image'] = docker_image_name
        container['env'][0]['value'] = 'run_master'

        payload = {'log_level': 'DEBUG'}
        container['env'][1]['value'] = utils.dict_to_b64str(payload)

        if not all(key in self.singularity_config for key in ["docker_user", "docker_password"]):
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

    # Detect if granularity, memory or runtime image changed or not
    def _has_config_changed(self, runtime_mem):
        config_granularity = False if self.singularity_config['worker_processes'] <= 1 else self.singularity_config['worker_processes']
        config_memory = self.singularity_config['runtime_memory'] if self.singularity_config['runtime_memory'] != 512 else False

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

            pod_mem_num = int(pod_mem_num)
            node_mem_num = int(float(node_mem_num) * 0.8)

            # There are pods with cpu granularity
            if multiples_pods_per_node:
                # Is lithops pod with granularity and the user doesn't want it
                if not config_granularity:
                    return True
                # There is granularity but the pod doesn't have the default memory
                if not config_memory and pod_mem_num != runtime_mem:
                    return True
                # There is granularity but the pod doesn't have the desired memory
                if config_memory and pod_mem_num != config_memory:
                    return True
            else:
                # There is a custom memory but the pod doesn't have the desired memory
                if config_memory:
                    if pod_mem_num != config_memory:
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
            granularity = job_payload['total_calls'] // len(self.nodes) \
                if self.singularity_config['worker_processes'] <= 1 else self.singularity_config['worker_processes']
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

            activation_id = f'lithops-{job_key.lower()}'

            job_res = yaml.safe_load(config.JOB_DEFAULT)
            job_res['metadata']['name'] = activation_id
            job_res['metadata']['namespace'] = self.namespace
            job_res['metadata']['labels']['version'] = 'lithops_v' + __version__
            job_res['metadata']['labels']['user'] = self.user

            job_res['spec']['activeDeadlineSeconds'] = self.singularity_config['runtime_timeout']
            job_res['spec']['parallelism'] = total_workers

            container = job_res['spec']['template']['spec']['containers'][0]
            container['image'] = docker_image_name
            if not docker_image_name.endswith(':latest'):
                container['imagePullPolicy'] = 'IfNotPresent'

            container['env'][0]['value'] = 'run_job'
            container['env'][1]['value'] = utils.dict_to_b64str(job_payload)
            container['env'][2]['value'] = master_ip

            container['resources']['requests']['memory'] = f'{runtime_memory}Mi'
            container['resources']['requests']['cpu'] = str(self.singularity_config['runtime_cpu'])
            container['resources']['limits']['memory'] = f'{runtime_memory}Mi'
            container['resources']['limits']['cpu'] = str(self.singularity_config['runtime_cpu'])

            logger.debug(f'ExecutorID {executor_id} | JobID {job_id} - Going '
                         f'to run {total_calls} activations in {total_workers} workers')

            if not all(key in self.singularity_config for key in ["docker_user", "docker_password"]):
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

        if not all(key in self.singularity_config for key in ["docker_user", "docker_password"]):
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

    # TODO
    def get_runtime_info(self):
        """
        Method that returns all the relevant information about the runtime set
        in config
        """
        if 'runtime' not in self.singularity_config or self.singularity_config['runtime'] == 'default':
            self.singularity_config['runtime'] = self._get_default_runtime_image_name()

        runtime_info = {
            'runtime_name': self.singularity_config['runtime']
        }

        return runtime_info
