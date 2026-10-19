#
# Unit tests for the Azure Functions, Azure Container Apps, Aliyun FC and Oracle Functions
# backend internals. No cloud account required; the SDKs and the az CLI are replaced by fakes.
#

import json
import os
import types

import pytest

from lithops.version import __version__


class FakeClock:
    """Replaces the time module of a backend; fails instead of hanging in an endless loop."""

    def __init__(self, max_sleeps=10000):
        self.now = 0.0
        self.sleeps = 0
        self.max_sleeps = max_sleeps

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps += 1
        if self.sleeps > self.max_sleeps:
            raise AssertionError('Loop without deadline')
        self.now += seconds


# /---------------------------------------------------------------------------/
# Azure Functions
# /---------------------------------------------------------------------------/

def _azure_functions_module():
    pytest.importorskip('azure.core')
    pytest.importorskip('azure.storage.queue')
    from lithops.serverless.backends.azure_functions import azure_functions
    return azure_functions


def _azure_functions_backend(trigger='pub/sub'):
    af = _azure_functions_module()
    backend = af.AzureFunctionAppBackend.__new__(af.AzureFunctionAppBackend)
    backend.name = 'azure_functions'
    backend.trigger = trigger
    backend.resource_group = 'rg'
    backend.storage_account_name = 'storageacc'
    backend.location = 'westeurope'
    backend.functions_version = 4
    backend.af_config = {'runtime_timeout': 300, 'runtime_memory': 2048, 'trigger': trigger}
    return af, backend


class FakeHTTPSConnection:
    status = 200
    reason = 'OK'
    body = 'invocation-id'

    def __init__(self, netloc, context=None):
        pass

    def request(self, method, route, body=None):
        pass

    def getresponse(self):
        return types.SimpleNamespace(
            status=self.status, reason=self.reason, read=lambda: self.body.encode('utf-8')
        )

    def close(self):
        pass


@pytest.mark.parametrize('status, reason', [(404, 'Not Found'), (500, 'Internal Server Error')])
def test_azure_functions_https_invoke_error_raises(monkeypatch, status, reason):
    af, backend = _azure_functions_backend(trigger='https')
    conn = type('Conn', (FakeHTTPSConnection,), {'status': status, 'reason': reason, 'body': 'boom'})
    monkeypatch.setattr(af.http.client, 'HTTPSConnection', conn)

    with pytest.raises(Exception, match=f'{status}.*boom'):
        backend.invoke('rt', 2048, {'call_ids': ['00000']})


def test_azure_functions_https_invoke_success_and_throttle(monkeypatch):
    af, backend = _azure_functions_backend(trigger='https')
    monkeypatch.setattr(af, 'time', FakeClock())

    monkeypatch.setattr(af.http.client, 'HTTPSConnection', FakeHTTPSConnection)
    assert backend.invoke('rt', 2048, {}) == 'invocation-id'

    throttled = type('Conn', (FakeHTTPSConnection,), {'status': 429, 'reason': 'Too Many Requests'})
    monkeypatch.setattr(af.http.client, 'HTTPSConnection', throttled)
    assert backend.invoke('rt', 2048, {}) is None


def test_azure_functions_pubsub_metadata_wait_has_deadline(monkeypatch):
    af, backend = _azure_functions_backend(trigger='pub/sub')
    backend.af_config['runtime_timeout'] = 30
    clock = FakeClock()
    monkeypatch.setattr(af, 'time', clock)

    queue = types.SimpleNamespace(
        send_message=lambda msg: types.SimpleNamespace(id='msg-id'),
        receive_message=lambda: None,
        clear_messages=lambda: None,
    )
    backend.queue_service = types.SimpleNamespace(get_queue_client=lambda name: queue)

    with pytest.raises(Exception, match='No response from function .* after 30 seconds'):
        backend.invoke('rt', 2048, {'get_metadata': True}, return_result=True)
    assert clock.now <= 32


def _az_list_response(*apps):
    return [{'Name': name, 'Tags': tags} for name, tags in apps]


def test_azure_functions_list_runtimes_by_runtime_name(monkeypatch):
    _, backend = _azure_functions_backend()
    app_name = backend._format_function_name('my-runtime', 4096)
    response = _az_list_response(
        (app_name, {'type': 'lithops-runtime', 'lithops_version': __version__,
                    'runtime_name': 'my-runtime', 'runtime_memory': '4096'}),
        ('lithops-worker-other', {'type': 'lithops-runtime', 'lithops_version': __version__,
                                  'runtime_name': 'other', 'runtime_memory': '512'}),
        ('not-lithops', {'type': 'web'}),
    )
    monkeypatch.setattr(backend, '_run_az_command', lambda cmd, **kw: response)

    assert backend.list_runtimes('my-runtime') == [('my-runtime', 4096, __version__, app_name)]
    assert len(backend.list_runtimes('all')) == 2
    assert backend.list_runtimes(app_name) == []


def test_azure_functions_runtime_memory_selects_app(monkeypatch, tmp_path):
    af, backend = _azure_functions_backend(trigger='pub/sub')

    assert backend.get_runtime_key('rt', 2048) != backend.get_runtime_key('rt', 4096)
    # Requested sizes that map to the same Flex instance memory share the app
    assert backend.get_runtime_key('rt', 1024) == backend.get_runtime_key('rt', 2048)
    default_name = backend._format_function_name('default-runtime-v314', 4096, '3.6.5.dev0')
    assert len(default_name) <= 60

    monkeypatch.setattr(af.config, 'BUILD_DIR', str(tmp_path))
    os.makedirs(os.path.join(backend._format_build_dir('rt'), af.config.ACTION_DIR))

    commands, published = [], []
    monkeypatch.setattr(backend, '_function_app_exists', lambda name: True)
    monkeypatch.setattr(backend, '_run_az_command', lambda cmd, **kw: commands.append(cmd))
    monkeypatch.setattr(backend, '_ensure_queue', lambda name: None)

    def publish(function_name, build_dir):
        fn_file = os.path.join(build_dir, af.config.ACTION_DIR, 'function.json')
        with open(fn_file) as f:
            bindings = json.load(f)['bindings']
        published.append((function_name, bindings[0]['queueName']))
    monkeypatch.setattr(backend, '_publish_function', publish)

    backend._create_function('rt', 2048, 300)
    backend._create_function('rt', 4096, 300)

    (name_2048, queue_2048), (name_4096, queue_4096) = published
    assert name_2048 == backend._format_function_name('rt', 2048)
    assert name_4096 == backend._format_function_name('rt', 4096)
    assert name_2048 != name_4096
    assert queue_2048 == backend._format_queue_name(name_2048, af.config.IN_QUEUE)
    assert queue_4096 == backend._format_queue_name(name_4096, af.config.IN_QUEUE)
    assert queue_2048 != queue_4096


def test_azure_functions_create_tags_runtime_memory(monkeypatch, tmp_path):
    af, backend = _azure_functions_backend(trigger='https')
    monkeypatch.setattr(af.config, 'BUILD_DIR', str(tmp_path))
    os.makedirs(os.path.join(backend._format_build_dir('rt'), af.config.ACTION_DIR))

    commands = []
    monkeypatch.setattr(backend, '_function_app_exists', lambda name: False)
    monkeypatch.setattr(backend, '_run_az_command', lambda cmd, **kw: commands.append(cmd))
    monkeypatch.setattr(backend, '_publish_function', lambda name, build_dir: None)

    backend._create_function('rt', 3000, 300)

    create_cmd = next(cmd for cmd in commands if cmd.startswith('az functionapp create'))
    assert '--instance-memory 4096' in create_cmd
    assert 'runtime_memory=4096' in create_cmd


def test_azure_functions_delete_legacy_app_by_tags(monkeypatch):
    _, backend = _azure_functions_backend()
    legacy_name = 'lithops-worker-rt-365dev0-0123456789ab'
    response = _az_list_response(
        (legacy_name, {'type': 'lithops-runtime', 'lithops_version': __version__, 'runtime_name': 'rt'}),
    )
    commands = []

    def run_az(cmd, return_json=False, **kw):
        if return_json:
            return response
        commands.append(cmd)
    monkeypatch.setattr(backend, '_run_az_command', run_az)
    backend.queue_service = types.SimpleNamespace(delete_queue=lambda name: None)

    assert backend.list_runtimes('rt') == [('rt', 2048, __version__, legacy_name)]
    backend.delete_runtime('rt', 2048, __version__)
    assert commands == [f'az functionapp delete --name {legacy_name} --resource-group rg']


# /---------------------------------------------------------------------------/
# Azure Container Apps
# /---------------------------------------------------------------------------/

def test_azure_containers_list_runtimes_by_runtime_name(monkeypatch):
    pytest.importorskip('azure.storage.queue')
    from lithops.serverless.backends.azure_containers import azure_containers as ac

    backend = ac.AzureContainerAppBackend.__new__(ac.AzureContainerAppBackend)
    backend.storage_account_name = 'storageacc'
    backend.trigger = 'pub/sub'
    image = 'docker.io/user/lithops-azurecontainers-default:latest'
    app_name = backend._format_containerapp_name(image, 1024)
    response = [
        {'Name': app_name, 'Tags': {'type': 'lithops-runtime', 'lithops_version': __version__,
                                    'runtime_name': image, 'runtime_memory': '1024'}},
        {'Name': 'lithops-worker-other', 'Tags': {'type': 'lithops-runtime', 'lithops_version': __version__,
                                                  'runtime_name': 'other:latest', 'runtime_memory': '512'}},
    ]
    monkeypatch.setattr(backend, '_run_az_command', lambda cmd, **kw: response)

    runtimes = backend.list_runtimes(image)
    assert runtimes == [(image, 1024, __version__, app_name)]
    assert runtimes[0][1] in ac.config.ALLOWED_MEM
    assert len(backend.list_runtimes('all')) == 2


# /---------------------------------------------------------------------------/
# Aliyun Function Compute
# /---------------------------------------------------------------------------/

def test_aliyun_fc_metadata_retry_resends_payload(monkeypatch):
    pytest.importorskip('alibabacloud_fc20230330')
    from lithops.serverless.backends.aliyun_fc import aliyun_fc

    backend = aliyun_fc.AliyunFunctionComputeBackend.__new__(aliyun_fc.AliyunFunctionComputeBackend)
    backend.deploy_mode = 'zip'
    monkeypatch.setattr(aliyun_fc, 'time', FakeClock())

    bodies = []
    meta = {'preinstalls': [], 'python_version': '3.12'}

    def invoke_function_with_options(function_name, request, headers, runtime):
        bodies.append(request.body.read())
        if len(bodies) == 1:
            raise aliyun_fc.FCClientException(status_code=412, code='PreconditionFailed', message='pending')
        return types.SimpleNamespace(body=json.dumps(meta).encode('utf-8'), headers={})
    backend.fc_client = types.SimpleNamespace(invoke_function_with_options=invoke_function_with_options)

    assert backend._generate_runtime_meta('lithops-worker-fn', max_attempts=3, retry_sleep=1) == meta
    assert len(bodies) == 2
    assert bodies[0] == bodies[1]
    assert json.loads(bodies[1])['get_metadata'] is True


# /---------------------------------------------------------------------------/
# Oracle Functions
# /---------------------------------------------------------------------------/

def test_oracle_invoke_uses_function_of_its_runtime_memory(monkeypatch):
    pytest.importorskip('oci')
    from lithops.serverless.backends.oracle_f import oracle_f

    backend = oracle_f.OracleCloudFunctionsBackend.__new__(oracle_f.OracleCloudFunctionsBackend)
    backend.config = {}
    backend.user = 'ocid1.user.oc1..aaaa'
    backend.region = 'eu-madrid-1'
    backend.namespace = 'ns'
    backend.app_id = 'app-id'
    backend.app_name = 'lithops_app'
    backend.invoke_functions = {}

    function_ids = {
        backend._format_function_name(backend._format_image_name('rt'), 256): 'fn-256',
        backend._format_function_name(backend._format_image_name('rt'), 1024): 'fn-1024',
    }
    monkeypatch.setattr(backend, '_get_function_id', lambda name: function_ids.get(name))
    backend.cf_client = types.SimpleNamespace(get_function=lambda function_id: types.SimpleNamespace(
        data=types.SimpleNamespace(lifecycle_state='ACTIVE', invoke_endpoint=f'https://{function_id}')
    ))

    invoked = []

    def invoke_client(endpoint):
        def invoke_function(function_id, invoke_function_body, fn_invoke_type):
            invoked.append((endpoint, function_id))
            return types.SimpleNamespace(status=202, headers={'Fn-Call-Id': f'call-{function_id}'})
        return types.SimpleNamespace(invoke_function=invoke_function)
    monkeypatch.setattr(backend, '_init_functions_invk_client', invoke_client)

    backend.pre_invoke('rt', 256)
    backend.pre_invoke('rt', 1024)

    # Calls of the 256MB job still queued after the 1024MB job started
    assert backend.invoke('rt', 256, {}) == 'call-fn-256'
    assert backend.invoke('rt', 1024, {}) == 'call-fn-1024'

    backend.invoke_functions.clear()
    assert backend.invoke('rt', 256, {}) == 'call-fn-256'
    assert invoked == [('https://fn-256', 'fn-256'), ('https://fn-1024', 'fn-1024'), ('https://fn-256', 'fn-256')]
