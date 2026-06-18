#
# (C) Copyright IBM Corp. 2020
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
import re
import hashlib
import json
import time
import logging
import copy

from ibm_cloud_sdk_core import ApiException
from ibm_code_engine_sdk.code_engine_v2 import (
    CodeEngineV2,
    EnvVarPrototype,
    SecretDataRegistrySecretData,
)

from lithops import utils
from lithops.config import dump_yaml_config, load_yaml_config
from lithops.version import __version__
from lithops.constants import CACHE_DIR, COMPUTE_CLI_MSG, JOBS_PREFIX

from . import config

logger = logging.getLogger(__name__)


# Decorator to wrap a function to reinit clients and retry on except.
def retry_on_except(func):
    def decorated_func(*args, **kwargs):
        _self = args[0]
        connection_retries = _self.config.get('connection_retries')
        if not connection_retries:
            return func(*args, **kwargs)

        ex = None
        for retry in range(connection_retries):
            try:
                return func(*args, **kwargs)
            except ApiException as e:
                if e.status_code == 409:
                    ex = e
                    logger.debug(f"Encountered conflict error {e.message}, ignoring")
                elif e.status_code == 500:
                    ex = e
                    logger.exception(
                        f'Got exception {e}, retrying for the {retry} time, '
                        f'left retries {connection_retries - 1 - retry}'
                    )
                else:
                    logger.debug(
                        f'Got exception {e} when trying to invoke {func.__name__}, raising'
                    )
                    raise e
                time.sleep(5)
        raise ex
    return decorated_func


class CodeEngineBackend:
    """
    A wrap-up around Code Engine backend.
    """

    def __init__(self, ce_config, internal_storage):
        logger.debug("Creating IBM Code Engine client")
        self.name = 'code_engine'
        self.type = utils.BackendType.BATCH.value
        self.config = ce_config
        self.internal_storage = internal_storage

        self.iam_api_key = ce_config['iam_api_key']
        self.namespace = ce_config.get('namespace')
        self.region = ce_config['region']

        self.user_key = re.sub(r'[^a-z0-9\-\.]', '0', self.iam_api_key[:4].lower())
        self.project_name = ce_config.get('project_name', f'lithops-{self.region}-{self.user_key}')
        self.project_id = ce_config.get('project_id')

        self.config['project_name'] = self.project_name

        self.ce_client = None
        self.cache_file = os.path.join(CACHE_DIR, self.name, self.project_name + '_data')
        self.jobs = []

        msg = COMPUTE_CLI_MSG.format('IBM Code Engine')
        logger.info(f"{msg} - Project: {self.project_name} - Region: {self.region}")

    def _create_code_engine_client(self):
        """
        Creates the Code Engine SDK client
        """
        if self.ce_client:
            return

        from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

        authenticator = IAMAuthenticator(self.iam_api_key)
        self.ce_client = CodeEngineV2(authenticator=authenticator)
        self.ce_client.set_service_url(config.BASE_URL_V2.format(self.region))

    def _get_or_create_namespace(self, create=True):
        """
        Gets or creates the Code Engine project.
        Namespace is kept for runtime key compatibility.
        """
        ce_data = load_yaml_config(self.cache_file)
        if not self.project_id:
            self.project_id = ce_data.get('project_id')
        if not self.namespace:
            self.namespace = ce_data.get('namespace')

        if self.project_id:
            self._sync_project_config()
            return self.namespace

        self._create_code_engine_client()

        response = self.ce_client.list_projects().get_result()
        for project in response.get('projects', []):
            if project['name'] == self.project_name:
                logger.debug(f"Found Code Engine project: {self.project_name}")
                self.project_id = project['id']
                break

        if not self.project_id and create:
            logger.debug(f"Creating new Code Engine project: {self.project_name}")
            response = self.ce_client.create_project(
                name=self.project_name,
                resource_group_id=self.config['resource_group_id']
            ).get_result()
            self.project_id = response['id']

        if not self.project_id:
            return None

        self._sync_project_config()

        ce_data['project_name'] = self.project_name
        ce_data['project_id'] = self.project_id
        ce_data['namespace'] = self.namespace
        dump_yaml_config(self.cache_file, ce_data)

        return self.namespace

    def _sync_project_config(self):
        """
        Syncs project and namespace metadata into the backend config
        """
        self.namespace = self.namespace or self.project_id
        self.config['project_id'] = self.project_id
        self.config['namespace'] = self.namespace
        self._create_code_engine_client()

    @staticmethod
    def _format_memory(memory_mb):
        """
        Code Engine expects memory in G/M units using supported GB values
        (e.g. 256 MB -> 0.25G, not 256M).
        """
        gb = memory_mb / 1024
        if gb == int(gb):
            return f'{int(gb)}G'
        text = f'{gb:.3f}'.rstrip('0').rstrip('.')
        return f'{text}G'

    @staticmethod
    def _format_cpu(cpu):
        """
        Formats CPU value for the Code Engine API
        """
        text = f'{cpu:.3f}'.rstrip('0').rstrip('.')
        return text

    @staticmethod
    def _parse_memory(memory_limit):
        """
        Parses a Code Engine memory limit back to MB
        """
        if not memory_limit:
            return 0
        if memory_limit.endswith('G'):
            mb = round(float(memory_limit[:-1]) * 1024)
        elif memory_limit.endswith('M'):
            mb = int(float(memory_limit[:-1]))
        else:
            mb = int(float(memory_limit))
        return CodeEngineBackend._normalize_memory_mb(mb)

    @staticmethod
    def _normalize_memory_mb(memory_mb):
        """
        Snaps parsed memory to the nearest valid Lithops memory tier
        """
        return min(config.VALID_MEMORY_VALUES, key=lambda v: abs(v - memory_mb))

    def _format_jobdef_name(self, runtime_name, runtime_memory, version=__version__):
        """
        Formats the job definition name
        """
        name = f'{runtime_name}-{runtime_memory}-{version}'
        name_hash = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
        return f'lithops-worker-{self.user_key}-{version.replace(".", "")}-{name_hash}'

    def _get_default_runtime_image_name(self):
        """
        Generates the default runtime image name
        """
        return utils.get_default_container_name(
            self.name, self.config, 'lithops-codeenigne-default'
        )

    def _has_registry_credentials(self):
        """
        Checks whether container registry credentials are set in config
        """
        return all(key in self.config for key in ["docker_user", "docker_password"])

    def _build_job_env_variables(self, action, payload_config_map_name=None):
        """
        Builds the environment variables passed to a Code Engine job run
        """
        env_variables = [
            EnvVarPrototype(name='ACTION', type='literal', value=action),
            EnvVarPrototype(name='LITHOPS_RUNTIME_TYPE', type='literal', value=config.LITHOPS_RUNTIME_TYPE),
            EnvVarPrototype(name='LITHOPS_VERSION', type='literal', value=__version__),
        ]
        if payload_config_map_name:
            env_variables.append(
                EnvVarPrototype(
                    name='PAYLOAD',
                    type='config_map_key_reference',
                    reference=payload_config_map_name,
                    key='lithops.payload',
                )
            )
        return env_variables

    def _list_jobs(self):
        """
        Lists all job definitions in the current project
        """
        try:
            return self.ce_client.list_jobs(self.project_id).get_result().get('jobs', [])
        except ApiException as e:
            logger.debug(f"List all jobs failed with {e.status_code} {e.message}")
            return []

    def _is_lithops_job(self, job):
        """
        Returns whether a job definition was created by Lithops
        """
        fn_name = job.get('name') or ''
        return fn_name.startswith(f'lithops-worker-{self.user_key}')

    @staticmethod
    def _read_job_env(job):
        """
        Reads Lithops runtime metadata from a job definition env vars
        """
        runtime_type = None
        version = __version__
        for env_var in job.get('run_env_variables', []):
            if env_var.get('name') == 'LITHOPS_RUNTIME_TYPE':
                runtime_type = env_var.get('value')
            elif env_var.get('name') == 'LITHOPS_VERSION':
                version = env_var.get('value', version)
        return runtime_type, version

    def _iter_lithops_runtimes(self, docker_image_name='all'):
        """
        Yields deployed Lithops runtimes as
        (image_name, memory, version, jobdef_name) tuples
        """
        for job in self._list_jobs():
            if not self._is_lithops_job(job):
                continue

            runtime_type, version = self._read_job_env(job)
            if runtime_type != config.LITHOPS_RUNTIME_TYPE:
                continue

            image_name = job.get('image_reference') or ''
            if docker_image_name != 'all' and docker_image_name not in image_name:
                continue

            memory = self._parse_memory(job.get('scale_memory_limit'))
            yield image_name, memory, version, job['name']

    def _delete_job_run(self, jobrun_name):
        """
        Deletes a job run, ignoring 404 errors
        """
        try:
            self.ce_client.delete_job_run(self.project_id, jobrun_name)
        except ApiException as e:
            if e.status_code != 404:
                logger.debug(f"Deleting job run {jobrun_name} failed with {e.status_code} {e.message}")

    def _delete_job_definition(self, jobdef_name):
        """
        Deletes a job definition, ignoring 404 errors
        """
        try:
            self.ce_client.delete_job(self.project_id, jobdef_name)
        except ApiException as e:
            if e.status_code != 404:
                logger.debug(f"Deleting job {jobdef_name} failed with {e.status_code} {e.message}")

    def _delete_config_map(self, config_map_name):
        """
        Deletes a configmap
        """
        try:
            logger.debug(f"Deleting ConfigMap {config_map_name}")
            self.ce_client.delete_config_map(self.project_id, config_map_name)
        except ApiException as e:
            logger.debug(f"Deleting config map {config_map_name} failed with {e.status_code} {e.message}")

    def _delete_lithops_config_maps(self):
        """
        Deletes leftover lithops config maps from the project
        """
        try:
            configmaps = self.ce_client.list_config_maps(self.project_id).get_result()
        except ApiException as e:
            logger.debug(f"Listing config maps failed with {e.status_code} {e.message}")
            return

        lithops_configmaps = [
            configmap['name']
            for configmap in configmaps.get('config_maps', [])
            if configmap.get('name', '').startswith('lithops')
        ]
        if not lithops_configmaps:
            return

        logger.debug(f'Deleting {len(lithops_configmaps)} leftover lithops config map(s)')
        for config_name in lithops_configmaps:
            self._delete_config_map(config_name)

    @staticmethod
    def _job_run_failure_message(status_details):
        """
        Extracts the failure reason from a job run status
        """
        for details in (status_details.get('indices_details') or {}).values():
            if not isinstance(details, dict):
                continue
            message = (
                details.get('last_failure_reason')
                or details.get('message')
                or details.get('reason')
            )
            if message:
                return message
        return ''

    @staticmethod
    def _job_run_finished(job_run):
        """
        Returns the job run state and its status details
        """
        status = job_run.get('status')
        status_details = job_run.get('status_details') or {}
        succeeded = status_details.get('succeeded') or 0
        failed_count = status_details.get('failed') or 0
        requested = status_details.get('requested') or 1

        if status == 'completed' or succeeded >= requested:
            return 'completed', status_details
        if status == 'failed' or (failed_count > 0 and status not in ('pending', 'running')):
            return 'failed', status_details
        return 'running', status_details

    def _wait_for_job_run(self, jobrun_name):
        """
        Waits until a job run completes or raises if it fails
        """
        logger.debug(f"Waiting for job run {jobrun_name}")
        while True:
            try:
                job_run = self.ce_client.get_job_run(self.project_id, jobrun_name).get_result()
            except ApiException as e:
                logger.debug(f"Polling job run {jobrun_name} failed with {e.status_code} {e.message}")
                time.sleep(config.JOB_RUN_POLL_INTERVAL)
                continue

            state, status_details = self._job_run_finished(job_run)
            if state == 'completed':
                logger.debug(f"Job run {jobrun_name} completed")
                return
            if state == 'failed':
                reason = self._job_run_failure_message(status_details)
                raise Exception(
                    f"Job run {jobrun_name} failed"
                    + (f": {reason}" if reason else '')
                )
            time.sleep(config.JOB_RUN_POLL_INTERVAL)

    @retry_on_except
    def _create_config_map(self, config_map_name, payload):
        """
        Creates a configmap
        """
        data = {'lithops.payload': utils.dict_to_b64str(payload)}
        logger.debug(f"Creating ConfigMap {config_map_name}")

        try:
            self.ce_client.create_config_map(
                self.project_id,
                config_map_name,
                data=data,
            )
        except ApiException as e:
            if e.status_code == 409:
                self.ce_client.replace_config_map(
                    self.project_id,
                    config_map_name,
                    data=data,
                )
            else:
                raise e

        return config_map_name

    @retry_on_except
    def _job_def_exists(self, jobdef_name):
        """
        Checks whether a job definition already exists
        """
        logger.debug(f"Checking if job definition {jobdef_name} already exists")
        try:
            self.ce_client.get_job(self.project_id, jobdef_name)
        except ApiException as e:
            if e.status_code == 404:
                logger.debug(f"Job definition {jobdef_name} not found (404)")
                return False
            raise e

        logger.debug(f"Job definition {jobdef_name} found")
        return True

    def build_runtime(self, docker_image_name, dockerfile, extra_args=[]):
        """
        Builds a new runtime from a Docker file and pushes it to the Docker hub
        """
        logger.info(f'Building runtime {docker_image_name} from {dockerfile}')

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

        docker_user = self.config.get("docker_user")
        docker_password = self.config.get("docker_password")
        docker_server = self.config.get("docker_server")

        logger.debug(f'Pushing runtime {docker_image_name} to container registry')

        if docker_user and docker_password:
            logger.debug('Container registry credentials found in config. Logging in into the registry')
            utils.docker_login(docker_user, docker_password, docker_server)

        if utils.is_podman(docker_path):
            cmd = f'{docker_path} push {docker_image_name} --format docker --remove-signatures'
        else:
            cmd = f'{docker_path} push {docker_image_name}'
        utils.run_command(cmd)

        logger.debug('Building done!')

    def _build_default_runtime(self, default_runtime_img_name):
        """
        Builds the default runtime
        """
        dockerfile = "Dockefile.default-ce-runtime"
        python_version = utils.CURRENT_PY_VERSION
        base_image = "slim-bookworm"
        with open(dockerfile, 'w') as f:
            f.write(f"FROM python:{python_version}-{base_image}\n")
            f.write(config.DOCKERFILE_DEFAULT)
        try:
            self.build_runtime(default_runtime_img_name, dockerfile)
        finally:
            os.remove(dockerfile)

    def deploy_runtime(self, docker_image_name, memory, timeout):
        """
        Deploys a new runtime from an already built Docker image
        """
        self._get_or_create_namespace()

        try:
            default_image_name = self._get_default_runtime_image_name()
        except Exception:
            default_image_name = None

        if docker_image_name == default_image_name:
            self._build_default_runtime(docker_image_name)

        logger.debug(f"Deploying runtime: {docker_image_name} - Memory: {memory} Timeout: {timeout}")
        self._create_job_definition(docker_image_name, memory, timeout)
        return self._generate_runtime_meta(docker_image_name, memory)

    def _generate_runtime_meta(self, docker_image_name, memory):
        """
        Extracts runtime metadata by running a metadata job in Code Engine
        """
        logger.info(f"Extracting metadata from: {docker_image_name}")
        jobdef_name = self._format_jobdef_name(docker_image_name, memory)

        job_payload = copy.deepcopy(self.internal_storage.storage.config)
        job_payload['log_level'] = logger.getEffectiveLevel()
        job_payload['runtime_name'] = jobdef_name

        config_map_name = self._create_config_map(f'lithops-{jobdef_name}-metadata', job_payload)

        try:
            self._delete_job_run(config.METADATA_JOBRUN_NAME)
            self._run_job(
                jobdef_name=jobdef_name,
                jobrun_name=config.METADATA_JOBRUN_NAME,
                total_workers=1,
                runtime_memory=memory,
                action='metadata',
                payload_config_map_name=config_map_name,
            )
            self._wait_for_job_run(config.METADATA_JOBRUN_NAME)
        except Exception as e:
            raise Exception(
                f"Unable to extract Python preinstalled modules from the runtime: {e}"
            ) from e
        finally:
            self._delete_job_run(config.METADATA_JOBRUN_NAME)
            self._delete_config_map(config_map_name)

        data_key = '/'.join([JOBS_PREFIX, jobdef_name + '.meta'])
        json_str = self.internal_storage.get_data(key=data_key)
        runtime_meta = json.loads(json_str.decode("ascii"))
        self.internal_storage.del_data(key=data_key)
        return runtime_meta

    def _create_container_registry_secret(self):
        """
        Create the container registry secret in the project
        (only if credentials are present in config)
        """
        if not self._has_registry_credentials():
            return

        logger.debug('Creating container registry secret')
        secret_data = SecretDataRegistrySecretData(
            server=self.config['docker_server'],
            username=self.config['docker_user'],
            password=self.config['docker_password'],
        )

        try:
            self.ce_client.delete_secret(self.project_id, config.REGISTRY_SECRET_NAME)
        except ApiException as e:
            if e.status_code != 404:
                raise e

        try:
            self.ce_client.create_secret(
                self.project_id,
                format='registry',
                name=config.REGISTRY_SECRET_NAME,
                data=secret_data,
            )
        except ApiException as e:
            if e.status_code != 409:
                raise e

    @retry_on_except
    def _create_job_definition(self, docker_image_name, runtime_memory, timeout=None):
        """
        Creates a Job definition
        """
        self._create_container_registry_secret()

        jobdef_name = self._format_jobdef_name(docker_image_name, runtime_memory)
        logger.debug(f"Creating job definition {jobdef_name}")

        try:
            self.ce_client.delete_job(self.project_id, jobdef_name)
        except ApiException as e:
            if e.status_code != 404:
                raise e

        while self._job_def_exists(jobdef_name):
            time.sleep(1)

        kwargs = {
            'run_commands': [config.PYTHON_BIN],
            'run_arguments': [config.ENTRYPOINT_SCRIPT],
            'run_env_variables': self._build_job_env_variables('run'),
            'run_mode': 'task',
            'scale_array_spec': '0',
            'scale_max_execution_time': timeout or self.config['runtime_timeout'],
            'scale_memory_limit': self._format_memory(runtime_memory),
            'scale_cpu_limit': self._format_cpu(self.config['runtime_cpu']),
            'scale_retry_limit': 3,
        }
        if self._has_registry_credentials():
            kwargs['image_secret'] = config.REGISTRY_SECRET_NAME

        self.ce_client.create_job(
            self.project_id,
            name=jobdef_name,
            image_reference=docker_image_name,
            **kwargs,
        )

        logger.debug(f'Job Definition {jobdef_name} created')
        return jobdef_name

    def _resolve_jobdef_name(self, runtime_name, memory, version=__version__):
        """
        Resolves the job definition name for a runtime image
        """
        jobdef_name = self._format_jobdef_name(runtime_name, memory, version)
        if self._job_def_exists(jobdef_name):
            return jobdef_name

        logger.debug(
            f"Job definition {jobdef_name} not found, searching by image {runtime_name}"
        )
        for image_name, _, job_version, fn_name in self._iter_lithops_runtimes('all'):
            if job_version != version:
                continue
            if runtime_name in image_name or image_name in runtime_name:
                logger.debug(f"Resolved job definition {fn_name} for runtime {runtime_name}")
                return fn_name

        return jobdef_name

    def delete_runtime(self, runtime_name, memory, version=__version__, jobdef_name=None):
        """
        Deletes a runtime.
        We need to delete the job definition.
        """
        if not self._get_or_create_namespace(create=False):
            logger.info(f"Project {self.project_name} does not exist")
            return

        if not jobdef_name:
            jobdef_name = self._resolve_jobdef_name(runtime_name, memory, version)

        logger.info(f'Deleting runtime: {runtime_name} - {memory}MB')
        self._delete_job_definition(jobdef_name)

    def clean(self, all=False):
        """
        Deletes all runtimes from all packages
        """
        logger.info(f'Cleaning project {self.project_name}')
        if not self._get_or_create_namespace(create=False):
            logger.info(f"Project {self.project_name} does not exist")
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
            return

        self.clear()
        for image_name, memory, version, jobdef_name in self.list_runtimes():
            self.delete_runtime(image_name, memory, version, jobdef_name=jobdef_name)

        self._delete_lithops_config_maps()

        if all and os.path.exists(self.cache_file):
            logger.info(f"Deleting Code Engine project: {self.project_name}")
            self.ce_client.delete_project(id=self.project_id)
            os.remove(self.cache_file)

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes
        return: list of tuples (docker_image_name, memory, version, jobdef_name)
        """
        if not self._get_or_create_namespace(create=False):
            logger.info(f"Project {self.project_name} does not exist")
            return []

        return list(self._iter_lithops_runtimes(docker_image_name))

    def clear(self, job_keys=None):
        """
        Clean all completed jobruns in the current executor
        """
        if not self._get_or_create_namespace(create=False):
            logger.info(f"Project {self.project_name} does not exist")
            return

        for job_key in job_keys or self.jobs:
            jobrun_name = f'lithops-{job_key.lower()}'
            self._delete_job_run(jobrun_name)
            self._delete_config_map(jobrun_name)
            try:
                self.jobs.remove(job_key)
            except ValueError:
                pass

    def invoke(self, docker_image_name, runtime_memory, job_payload):
        """
        Invoke -- return information about this invocation
        For array jobs only remote_invocator is allowed
        """
        self._get_or_create_namespace()

        executor_id = job_payload['executor_id']
        job_id = job_payload['job_id']
        job_key = job_payload['job_key']
        self.jobs.append(job_key)

        total_calls = job_payload['total_calls']
        chunksize = job_payload['chunksize']
        max_workers = job_payload['max_workers']

        total_workers = total_calls // chunksize + (total_calls % chunksize > 0)
        if max_workers < total_workers:
            chunksize = total_calls // max_workers + (total_calls % max_workers > 0)
            total_workers = total_calls // chunksize + (total_calls % chunksize > 0)
            job_payload['chunksize'] = chunksize

        logger.debug(
            f'ExecutorID {executor_id} | JobID {job_id} - Required Workers: {total_workers}'
        )

        jobdef_name = self._format_jobdef_name(docker_image_name, runtime_memory)
        if not self._job_def_exists(jobdef_name):
            self._create_job_definition(docker_image_name, runtime_memory)

        activation_id = f'lithops-{job_key.lower()}'
        config_map_name = self._create_config_map(activation_id, job_payload)

        self._run_job(
            jobdef_name=jobdef_name,
            jobrun_name=activation_id,
            total_workers=total_workers,
            runtime_memory=runtime_memory,
            action='run',
            payload_config_map_name=config_map_name,
        )

        return activation_id

    @retry_on_except
    def _run_job(self, jobdef_name, jobrun_name, total_workers, runtime_memory,
                 action, payload_config_map_name):
        """
        Creates and starts a Code Engine job run
        """
        self.ce_client.create_job_run(
            self.project_id,
            job_name=jobdef_name,
            name=jobrun_name,
            scale_array_spec=f'0-{total_workers - 1}',
            scale_max_execution_time=self.config['runtime_timeout'],
            scale_memory_limit=self._format_memory(runtime_memory),
            scale_cpu_limit=self._format_cpu(self.config['runtime_cpu']),
            run_env_variables=self._build_job_env_variables(action, payload_config_map_name),
        )

    def get_runtime_key(self, docker_image_name, runtime_memory, version=__version__):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        self._get_or_create_namespace()
        jobdef_name = self._format_jobdef_name(docker_image_name, 256, version)
        runtime_key = os.path.join(
            self.name, version, self.region, self.namespace, jobdef_name
        )
        return runtime_key

    def get_runtime_info(self):
        """
        Method that returns all the relevant information about the runtime set
        in config
        """
        if 'runtime' not in self.config or self.config['runtime'] == 'default':
            self.config['runtime'] = self._get_default_runtime_image_name()

        return {
            'runtime_name': self.config['runtime'],
            'runtime_cpu': self.config['runtime_cpu'],
            'runtime_memory': self.config['runtime_memory'],
            'runtime_timeout': self.config['runtime_timeout'],
            'max_workers': self.config['max_workers'],
        }
