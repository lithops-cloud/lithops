#
# Copyright Cloudlab URV 2020
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

import base64
import hashlib
import io
import json
import logging
import os
import re
import shutil
import subprocess as sp
import sys
import time

import lithops
from alibabacloud_fc20230330 import models as fc_models
from alibabacloud_fc20230330.client import Client as FC3Client
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_openapi.exceptions import ClientException as FCClientException
from darabonba.runtime import RuntimeOptions

from lithops import utils
from lithops.version import __version__
from lithops.constants import COMPUTE_CLI_MSG, TEMP_DIR

from . import config

logger = logging.getLogger(__name__)


def _init_fc3_client(access_key_id, access_key_secret, region, endpoint):
    cfg = open_api_models.Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        region_id=region,
        endpoint=endpoint,
    )
    return FC3Client(cfg)


def _is_not_found_error(exc):
    if isinstance(exc, FCClientException):
        return exc.status_code == 404 or exc.code in (
            'FunctionNotFound', 'ServiceNotFound', 'NotFound',
        )
    return False


def _is_pending_error(exc):
    if isinstance(exc, FCClientException):
        return exc.status_code == 412 or exc.code == 'PreconditionFailed'
    return False


def _read_invoke_body(response):
    body = response.body
    if body is None:
        return b''
    if hasattr(body, 'read'):
        return body.read()
    if isinstance(body, bytes):
        return body
    return str(body).encode('utf-8')


def _get_response_header(response, name):
    headers = response.headers or {}
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


class AliyunFunctionComputeBackend:
    """
    Lithops backend for Alibaba Cloud Function Compute 3.0 (API 2023-03-30).
    """

    def __init__(self, afc_config, internal_storage):
        logger.debug("Creating Aliyun Function Compute 3.0 client")
        self.name = 'aliyun_fc'
        self.type = utils.BackendType.FAAS.value
        self.config = afc_config
        self.role_arn = afc_config['role_arn']
        self.region = afc_config['region']

        self.fc_client = _init_fc3_client(
            afc_config['access_key_id'],
            afc_config['access_key_secret'],
            self.region,
            afc_config['public_endpoint'],
        )

        self.deploy_mode = self.config.get('deploy_mode', 'runtime')

        msg = COMPUTE_CLI_MSG.format('Aliyun Function Compute 3.0')
        logger.info(f"{msg} - Region: {self.region} - Deploy mode: {self.deploy_mode}")

    def _format_function_name(self, runtime_name, runtime_memory, version=__version__):
        name = f'{runtime_name}-{runtime_memory}-{version}'
        name_hash = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]

        return f'lithops-worker-{runtime_name}-v{version.replace(".", "-")}-{name_hash}'

    def _unformat_function_name(self, function_name):
        runtime_name, _hash = function_name.rsplit('-', 1)
        runtime_name = runtime_name.replace('lithops-worker-', '')
        runtime_name, version = runtime_name.rsplit('-v', 1)
        version = version.replace('-', '.')
        return version, runtime_name

    def _get_default_runtime_name(self):
        py_version = utils.CURRENT_PY_VERSION.replace('.', '')
        if self._use_custom_container():
            return f'default-container-runtime-v{py_version}'
        return f'default-python-runtime-v{py_version}'

    def _use_custom_container(self):
        return self.deploy_mode == 'custom-container'

    def _format_image_name(self, runtime_name, version=__version__):
        if '/' in runtime_name and ':' in runtime_name:
            return runtime_name

        docker_server = self.config.get('docker_server', 'docker.io')
        docker_user = self.config['docker_user']
        tag = f"v{version.replace('.', '-')}"
        image = f'lithops-aliyunfc-{runtime_name}:{tag}'

        if docker_server == 'docker.io':
            return f'{docker_user}/{image}'
        return f'{docker_server}/{docker_user}/{image}'

    def _list_functions(self, prefix='lithops-worker'):
        functions = []
        next_token = None

        while True:
            req = fc_models.ListFunctionsRequest(
                prefix=prefix,
                fc_version='v3',
                limit=100,
                next_token=next_token,
            )
            res = self.fc_client.list_functions(req)
            output = res.body
            if output and output.functions:
                functions.extend(output.functions)
            next_token = output.next_token if output else None
            if not next_token:
                break

        return functions

    def _get_function(self, function_name):
        res = self.fc_client.get_function(
            function_name, fc_models.GetFunctionRequest()
        )
        return res.body

    def _function_exists(self, function_name):
        try:
            self._get_function(function_name)
            return True
        except FCClientException as e:
            if _is_not_found_error(e):
                return False
            raise

    def _wait_for_function_active(self, function_name):
        """
        FC3 returns 412 if invoke runs while the function is still Pending
        (common for custom-container image pull).
        """
        max_wait = 900 if self._use_custom_container() else 300
        poll_interval = 5
        elapsed = 0

        while elapsed < max_wait:
            fn = self._get_function(function_name)
            state = (fn.state or '').strip()
            state_lower = state.lower()

            if state_lower in ('active', 'ready'):
                logger.debug('Function %s is ready (state=%s)', function_name, state)
                return

            if state_lower in ('failed', 'inactive'):
                raise Exception(
                    f'Function {function_name} is {state}: '
                    f'{fn.state_reason or ""} ({fn.state_reason_code or ""})'
                )

            logger.info(
                'Waiting for function %s to become active (state=%s, elapsed=%ss)...',
                function_name, state or 'pending', elapsed
            )
            time.sleep(poll_interval)
            elapsed += poll_interval

        raise Exception(
            f'Timed out after {max_wait}s waiting for function {function_name} '
            'to become active. Check the FC console (FC 3.0 functions list).'
        )

    def _delete_function_if_exists(self, function_name):
        if self._function_exists(function_name):
            logger.debug('Deleting function %s', function_name)
            self.fc_client.delete_function(function_name)

    def _zip_code_location(self, zip_path):
        with open(zip_path, 'rb') as zipf:
            encoded = base64.b64encode(zipf.read()).decode('utf-8')
        return fc_models.InputCodeLocation(zip_file=encoded)

    def _build_container_image(self, runtime_name, dockerfile, extra_args=None,
                               context_files=None):
        if extra_args is None:
            extra_args = []
        image_name = self._format_image_name(runtime_name)
        docker_path = utils.get_docker_path()
        if not docker_path:
            raise Exception('Docker is required to build custom-container runtimes for Aliyun FC')

        assert os.path.isfile(dockerfile), f'Cannot locate "{dockerfile}"'

        build_dir = os.path.join(config.BUILD_DIR, runtime_name)
        shutil.rmtree(build_dir, ignore_errors=True)
        os.makedirs(build_dir)

        if context_files:
            for src, dst in context_files.items():
                shutil.copy(src, os.path.join(build_dir, dst))

        current_location = os.path.dirname(os.path.abspath(__file__))
        handler_file = os.path.join(current_location, 'container_entry_point.py')
        utils.create_handler_zip(
            config.FH_ZIP_LOCATION, handler_file, 'container_entry_point.py'
        )
        shutil.copy(config.FH_ZIP_LOCATION, os.path.join(build_dir, 'lithops_aliyun_fc.zip'))
        shutil.copy(dockerfile, os.path.join(build_dir, 'Dockerfile'))

        cmd = (
            f'{docker_path} build --platform=linux/amd64 '
            f'-t {image_name} -f {os.path.join(build_dir, "Dockerfile")} {build_dir}'
        )
        cmd = f'{cmd} {" ".join(extra_args)}'.strip()
        logger.info('Building container image %s', image_name)
        utils.run_command(cmd)

        docker_password = self.config.get('docker_password')
        docker_server = self.config.get('docker_server', 'docker.io')
        if docker_password:
            docker_user = self.config['docker_user']
            logger.debug('Logging in to container registry %s', docker_server)
            utils.docker_login(docker_user, docker_password, docker_server)

        if utils.is_podman(docker_path):
            push_cmd = f'{docker_path} push {image_name} --format docker --remove-signatures'
        else:
            push_cmd = f'{docker_path} push {image_name}'
        logger.info('Pushing container image %s', image_name)
        push_output = sp.check_output(
            push_cmd, shell=True, stderr=sp.STDOUT, text=True
        )
        digest_match = re.search(r'digest:\s*(sha256:[a-f0-9]+)', push_output)
        if digest_match:
            image_name = f'{image_name}@{digest_match.group(1)}'
            logger.info('Using pinned container image %s', image_name)
        else:
            logger.warning(
                'Could not parse image digest from push output; '
                'FC may reuse a cached image layer'
            )

        if os.path.exists(config.FH_ZIP_LOCATION):
            os.remove(config.FH_ZIP_LOCATION)

        self._container_image = image_name
        return image_name

    def build_runtime(self, runtime_name, requirements_file, extra_args=None):
        if extra_args is None:
            extra_args = []
        if self._use_custom_container():
            if not requirements_file:
                raise Exception(
                    'Please provide a Dockerfile path or a requirements.txt file '
                    'for custom-container runtime builds'
                )
            basename = os.path.basename(requirements_file).lower()
            if 'dockerfile' in basename:
                return self._build_container_image(runtime_name, requirements_file, extra_args)

            dockerfile = os.path.join(config.BUILD_DIR, f'{runtime_name}.Dockerfile')
            os.makedirs(config.BUILD_DIR, exist_ok=True)
            with open(dockerfile, 'w') as df:
                df.write(f'FROM python:{utils.CURRENT_PY_VERSION}-slim-bookworm\n')
                df.write(config.DEFAULT_DOCKERFILE)
                df.write('COPY requirements.txt .\n')
                df.write('RUN pip install --no-cache-dir -r requirements.txt\n')
            try:
                return self._build_container_image(
                    runtime_name, dockerfile, extra_args,
                    context_files={requirements_file: 'requirements.txt'}
                )
            finally:
                if os.path.exists(dockerfile):
                    os.remove(dockerfile)

        if not requirements_file:
            raise Exception('Please provide a "requirements.txt" file with the necessary modules')

        logger.info(f'Building runtime {runtime_name} from {requirements_file}')

        build_dir = os.path.join(config.BUILD_DIR, runtime_name)

        shutil.rmtree(build_dir, ignore_errors=True)
        os.makedirs(build_dir)

        logger.debug("Downloading base modules (via pip install)")
        req_file = os.path.join(build_dir, 'requirements.txt')
        with open(req_file, 'w') as reqf:
            reqf.write(config.REQUIREMENTS_FILE)

        def download_requirements():
            cmd = f'{sys.executable} -m pip install -t {build_dir} -r {req_file} --no-deps'
            utils.run_command(cmd)

        if utils.is_linux_system():
            download_requirements()
        else:
            docker_path = utils.get_docker_path()
            if docker_path:
                cmd = 'python3 -m pip install -U -t . -r requirements.txt'
                cmd = f'docker run -w /tmp -v {build_dir}:/tmp python:{utils.CURRENT_PY_VERSION}-slim-bookworm {cmd}'
                utils.run_command(cmd)
            else:
                logger.warning('Aliyun Functions use a Linux environment. Building'
                               ' a runtime from a non-Linux environment might cause issues')
                download_requirements()

        current_location = os.path.dirname(os.path.abspath(__file__))
        handler_file = os.path.join(current_location, 'entry_point.py')
        shutil.copy(handler_file, build_dir)

        module_location = os.path.dirname(os.path.abspath(lithops.__file__))
        dst_location = os.path.join(build_dir, 'lithops')

        if os.path.isdir(dst_location):
            logger.warning("Using user specified 'lithops' module from the custom runtime folder. "
                           "Please refrain from including it as it will be automatically installed anyway.")
        else:
            shutil.copytree(module_location, dst_location, ignore=shutil.ignore_patterns('__pycache__'))

        os.chdir(build_dir)
        runtime_zip = f'{config.BUILD_DIR}/{runtime_name}.zip'
        if os.path.exists(runtime_zip):
            os.remove(runtime_zip)
        utils.run_command(f'zip -r {runtime_zip} .')
        shutil.rmtree(build_dir, ignore_errors=True)

    def _build_default_runtime(self, runtime_name):
        if self._use_custom_container():
            dockerfile = os.path.join(TEMP_DIR, 'aliyun_default.Dockerfile')
            with open(dockerfile, 'w') as df:
                df.write(f'FROM python:{utils.CURRENT_PY_VERSION}-slim-bookworm\n')
                df.write(config.DEFAULT_DOCKERFILE)
            try:
                self.build_runtime(runtime_name, dockerfile)
            finally:
                if os.path.exists(dockerfile):
                    os.remove(dockerfile)
            return

        requirements_file = os.path.join(TEMP_DIR, 'aliyun_default_requirements.txt')
        with open(requirements_file, 'w') as reqf:
            reqf.write(config.REQUIREMENTS_FILE)
        try:
            self.build_runtime(runtime_name, requirements_file)
        finally:
            os.remove(requirements_file)

    def _container_image_uri(self, runtime_name):
        return getattr(self, '_container_image', None) or self._format_image_name(runtime_name)

    def _create_function(self, function_name, memory, timeout, runtime_name):
        if self._use_custom_container():
            image_name = self._container_image_uri(runtime_name)
            function_input = fc_models.CreateFunctionInput(
                function_name=function_name,
                runtime='custom-container',
                handler='container_entry_point.invoke',
                custom_container_config=fc_models.CustomContainerConfig(
                    image=image_name,
                    acceleration_type='Default',
                    port=config.CA_PORT,
                ),
                memory_size=memory,
                timeout=timeout,
                role=self.role_arn,
                internet_access=True,
            )
        else:
            zip_path = f'{config.BUILD_DIR}/{runtime_name}.zip'
            function_input = fc_models.CreateFunctionInput(
                function_name=function_name,
                runtime=config.AVAILABLE_PY_RUNTIMES[utils.CURRENT_PY_VERSION],
                handler='entry_point.main',
                code=self._zip_code_location(zip_path),
                memory_size=memory,
                timeout=timeout,
                role=self.role_arn,
            )

        res = self.fc_client.create_function(
            fc_models.CreateFunctionRequest(body=function_input)
        )
        if res.body and res.body.function_name:
            logger.info(
                'Created function %s (state=%s)',
                res.body.function_name,
                res.body.state or 'pending',
            )

    def deploy_runtime(self, runtime_name, memory, timeout):
        logger.info(f"Deploying runtime: {runtime_name} - Memory: {memory} Timeout: {timeout}")

        self._container_image = None
        if runtime_name == self._get_default_runtime_name():
            self._build_default_runtime(runtime_name)

        function_name = self._format_function_name(runtime_name, memory)

        self._delete_function_if_exists(function_name)

        logger.debug('Creating function %s', function_name)
        self._create_function(function_name, memory, timeout, runtime_name)
        self._wait_for_function_active(function_name)
        if self._use_custom_container():
            time.sleep(10)

        metadata = self._generate_runtime_meta(function_name)

        return metadata

    def delete_runtime(self, runtime_name, memory, version=__version__):
        logger.info(f'Deleting runtime: {runtime_name} - {memory}MB')
        function_name = self._format_function_name(runtime_name, memory, version)
        self._delete_function_if_exists(function_name)

    def clean(self, **kwargs):
        logger.debug('Going to delete all deployed Lithops runtimes')
        for function in self._list_functions():
            if function.function_name.startswith('lithops-worker'):
                logger.info(f'Going to delete runtime {function.function_name}')
                self.fc_client.delete_function(function.function_name)

    def list_runtimes(self, runtime_name='all'):
        logger.debug('Listing deployed runtimes')
        runtimes = []

        for function in self._list_functions():
            if function.function_name.startswith('lithops-worker'):
                memory = function.memory_size
                version, img_name = self._unformat_function_name(function.function_name)
                if runtime_name == img_name or runtime_name == 'all':
                    runtimes.append((img_name, memory, version, function.function_name))
        return runtimes

    def invoke(self, runtime_name, memory, payload=None):
        if payload is None:
            payload = {}
        function_name = self._format_function_name(runtime_name, memory)
        payload_bytes = json.dumps(payload, default=str).encode('utf-8')

        headers = fc_models.InvokeFunctionHeaders(
            x_fc_invocation_type='Async',
        )
        request = fc_models.InvokeFunctionRequest(body=io.BytesIO(payload_bytes))

        res = self.fc_client.invoke_function_with_options(
            function_name, request, headers, RuntimeOptions()
        )

        request_id = _get_response_header(res, 'x-fc-request-id')
        if not request_id:
            raise Exception(f'Aliyun FC invoke did not return a request ID: {res.headers}')
        return request_id

    def _generate_runtime_meta(self, function_name):
        logger.info(f'Extracting runtime metadata from: {function_name}')
        payload = {'log_level': logger.getEffectiveLevel(), 'get_metadata': True}
        payload_bytes = json.dumps(payload, default=str).encode('utf-8')

        headers = fc_models.InvokeFunctionHeaders(
            x_fc_invocation_type='Sync',
        )
        request = fc_models.InvokeFunctionRequest(body=io.BytesIO(payload_bytes))

        last_error = None
        for attempt in range(60):
            try:
                res = self.fc_client.invoke_function_with_options(
                    function_name, request, headers, RuntimeOptions()
                )
                runtime_meta = json.loads(_read_invoke_body(res))
                if isinstance(runtime_meta, dict) and runtime_meta.get('errorMessage'):
                    last_error = runtime_meta['errorMessage']
                    logger.warning(
                        'Metadata invoke failed (attempt %s): %s',
                        attempt + 1, last_error,
                    )
                    time.sleep(10)
                    continue
                break
            except FCClientException as e:
                last_error = e
                if _is_pending_error(e):
                    logger.debug(
                        'Function %s not ready for invoke (attempt %s), retrying...',
                        function_name, attempt + 1,
                    )
                    time.sleep(5)
                    continue
                raise Exception(f'Unable to extract runtime metadata: {e}') from e
        else:
            raise Exception(
                f'Unable to extract runtime metadata from {function_name}: {last_error}'
            )

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        logger.debug("Metadata extracted successfully")
        return runtime_meta

    def get_runtime_key(self, runtime_name, runtime_memory, version=__version__):
        function_name = self._format_function_name(runtime_name, runtime_memory, version)
        runtime_key = os.path.join(self.name, version, self.region, function_name)

        return runtime_key

    def get_runtime_info(self):
        if not self._use_custom_container():
            if utils.CURRENT_PY_VERSION not in config.AVAILABLE_PY_RUNTIMES:
                raise Exception(
                    f'Python {utils.CURRENT_PY_VERSION} is not available for Aliyun '
                    f'Functions. Please use one of {list(config.AVAILABLE_PY_RUNTIMES.keys())}, '
                    "or set aliyun_fc.deploy_mode to 'custom-container'"
                )

        if 'runtime' not in self.config or self.config['runtime'] == 'default':
            self.config['runtime'] = self._get_default_runtime_name()

        runtime_info = {
            'runtime_name': self.config['runtime'],
            'runtime_memory': self.config['runtime_memory'],
            'runtime_timeout': self.config['runtime_timeout'],
            'max_workers': self.config['max_workers'],
        }

        return runtime_info
