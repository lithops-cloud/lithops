#
# Unit tests for the AWS Lambda and AWS Batch backend internals. No AWS account
# required: the boto3 clients are botocore stubs or mocks.
#

import re
from unittest.mock import MagicMock

import pytest

boto3 = pytest.importorskip('boto3')
botocore = pytest.importorskip('botocore')

from botocore.credentials import Credentials  # noqa: E402
from botocore.exceptions import ClientError, ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError  # noqa: E402
from botocore.stub import ANY, Stubber  # noqa: E402

from lithops.serverless.backends.aws_batch import config as batch_config  # noqa: E402
from lithops.serverless.backends.aws_batch.aws_batch import AWSBatchBackend  # noqa: E402
from lithops.serverless.backends.aws_lambda import aws_lambda as aws_lambda_module  # noqa: E402
from lithops.serverless.backends.aws_lambda import config as lambda_config  # noqa: E402
from lithops.serverless.backends.aws_lambda.aws_lambda import AWSLambdaBackend  # noqa: E402
from lithops.version import __version__  # noqa: E402

REGION = 'us-east-1'
USER_KEY = 'abcd'
CURRENT_PACKAGE = f'lithops_v{__version__.replace(".", "")}_{USER_KEY}'
OK = {'ResponseMetadata': {'HTTPStatusCode': 200}}


def _stubbed_client(service):
    client = boto3.client(
        service, region_name=REGION, aws_access_key_id='AKIDEXAMPLE', aws_secret_access_key='secret'
    )
    return client, Stubber(client)


# ---------------------------------------------------------------------------
# AWS Batch
# ---------------------------------------------------------------------------

def _batch_load_config(**overrides):
    cfg = {'aws_batch': {'execution_role': 'arn:role', 'security_groups': ['sg'], 'region': REGION, **overrides}}
    batch_config.load_config(cfg)
    return cfg['aws_batch']


def _make_batch_backend(namespace=None, **overrides):
    """Build an AWSBatchBackend without running __init__ (which calls STS)."""
    backend = AWSBatchBackend.__new__(AWSBatchBackend)
    backend.name = 'aws_batch'
    backend.region = REGION
    backend.aws_batch_config = {
        'runtime_cpu': 0.5, 'runtime_memory': 1024, 'execution_role': 'arn:exec', 'job_role': 'arn:job',
        'assign_public_ip': True, 'env_type': 'FARGATE_SPOT', **overrides
    }
    backend.env_type = backend.aws_batch_config['env_type']
    backend.namespace = namespace
    backend.account_id = '123456789012'
    backend.package = f'{CURRENT_PACKAGE}_{namespace}' if namespace else CURRENT_PACKAGE
    backend._queue_name = f'{backend.package}_queue'
    backend.batch_client = MagicMock()
    return backend


class TestBatchMaxWorkers:

    def test_default_max_workers_is_int(self):
        cfg = _batch_load_config()
        assert cfg['max_workers'] == 20
        assert isinstance(cfg['max_workers'], int)

    def test_array_job_size_is_int(self):
        backend = _make_batch_backend()
        backend.batch_client, stubber = _stubbed_client('batch')
        stubber.add_response(
            'submit_job', {'jobName': 'job', 'jobId': 'id'},
            {'jobName': ANY, 'jobQueue': ANY, 'jobDefinition': ANY,
             'arrayProperties': {'size': 20}, 'containerOverrides': ANY}
        )
        payload = {'executor_id': 'ex', 'job_id': 'A000', 'job_key': 'ex-A000',
                   'total_calls': 100, 'max_workers': 20.0, 'chunksize': 1}
        with stubber:
            backend.invoke('rt:latest', 1024, payload)
        stubber.assert_no_pending_responses()
        assert payload['chunksize'] == 5 and isinstance(payload['chunksize'], int)


class TestBatchJobDefinition:

    def _register_args(self, backend, runtime_memory):
        backend.batch_client.describe_job_definitions.return_value = {**OK, 'jobDefinitions': []}
        backend.batch_client.register_job_definition.return_value = OK
        backend._create_job_def('rt:latest', runtime_memory)
        return backend.batch_client.register_job_definition.call_args.kwargs

    def test_uses_requested_memory(self):
        backend = _make_batch_backend(runtime_cpu=1, runtime_memory=2048)
        kwargs = self._register_args(backend, 4096)
        resources = {r['type']: r['value'] for r in kwargs['containerProperties']['resourceRequirements']}
        assert resources == {'VCPU': '1', 'MEMORY': '4096'}
        assert kwargs['jobDefinitionName'].endswith('--4096mb')

    def test_fargate_rejects_invalid_requested_memory(self):
        backend = _make_batch_backend(runtime_cpu=0.5, runtime_memory=1024)
        with pytest.raises(Exception, match='runtime memory is not valid'):
            self._register_args(backend, 1536)
        backend.batch_client.register_job_definition.assert_not_called()

    def test_ec2_does_not_check_fargate_memory(self):
        backend = _make_batch_backend(env_type='EC2', runtime_cpu=1, runtime_memory=1024)
        kwargs = self._register_args(backend, 1536)
        assert kwargs['platformCapabilities'] == ['EC2']

    def test_an_existing_job_definition_is_replaced(self):
        backend = _make_batch_backend(runtime_cpu=1)
        name = backend._format_jobdef_name('rt:latest', 2048)
        backend.batch_client.describe_job_definitions.return_value = {**OK, 'jobDefinitions': [{
            'jobDefinitionName': name, 'jobDefinitionArn': 'arn:old', 'revision': 1, 'status': 'ACTIVE',
        }]}
        backend.batch_client.register_job_definition.return_value = {**OK, 'jobDefinitionArn': 'arn:new'}
        backend.batch_client.deregister_job_definition.return_value = OK
        backend._create_job_def('rt:latest', 2048)
        resources = {
            item['type']: item['value']
            for item in backend.batch_client.register_job_definition.call_args.kwargs[
                'containerProperties'
            ]['resourceRequirements']
        }
        assert resources['VCPU'] == '1'
        backend.batch_client.deregister_job_definition.assert_called_once_with(jobDefinition='arn:old')

    def test_job_queues_past_the_first_page(self):
        backend = _make_batch_backend()
        names = [f'{backend.package}_a', f'{backend.package}_b']
        backend.batch_client.describe_job_queues.side_effect = [
            {**OK, 'jobQueues': [{'jobQueueName': names[0]}], 'nextToken': 't'},
            {**OK, 'jobQueues': [{'jobQueueName': names[1]}]},
        ]
        assert [queue['jobQueueName'] for queue in backend._get_job_queue()] == names
        assert backend.batch_client.describe_job_queues.call_args_list[1].kwargs['nextToken'] == 't'

    def test_compute_environments_past_the_first_page(self):
        backend = _make_batch_backend()
        names = [f'{backend.package}_a', f'{backend.package}_b']
        backend.batch_client.describe_compute_environments.side_effect = [
            {**OK, 'computeEnvironments': [{'computeEnvironmentName': names[0]}], 'nextToken': 't'},
            {**OK, 'computeEnvironments': [{'computeEnvironmentName': names[1]}]},
        ]
        found = [env['computeEnvironmentName'] for env in backend._get_compute_env()]
        assert found == names
        assert backend.batch_client.describe_compute_environments.call_args_list[1].kwargs['nextToken'] == 't'


class TestBatchJobDefinitionName:

    @pytest.mark.parametrize('namespace', [None, 'dev'])
    def test_current_version_name_is_unchanged(self, namespace):
        backend = _make_batch_backend(namespace=namespace)
        package = f'{CURRENT_PACKAGE}_{namespace}' if namespace else CURRENT_PACKAGE
        name = backend._format_jobdef_name('batch-default-runtime-v310:latest', 1024)
        assert name == f'{package}--FARGATE_SPOT--batch-default-runtime-v310--latest--1024mb'

    @pytest.mark.parametrize('namespace', [None, 'dev'])
    def test_requested_version_is_used(self, namespace):
        backend = _make_batch_backend(namespace=namespace)
        name = backend._format_jobdef_name('rt:latest', 1024, '3.7.0')
        suffix = '_dev' if namespace else ''
        assert name == f'lithops_v370_{USER_KEY}{suffix}--FARGATE_SPOT--rt--latest--1024mb'

    @pytest.mark.parametrize('runtime_name', ['rt:latest', 'my-rt:v1_0', 'batch-default-runtime-v310:latest'])
    def test_round_trip(self, runtime_name):
        backend = _make_batch_backend(namespace='dev')
        name = backend._format_jobdef_name(runtime_name, 2048)
        assert re.fullmatch(r'[A-Za-z0-9_-]{1,128}', name)
        assert backend._unformat_jobdef_name(name) == (runtime_name, 2048, __version__)

    def test_list_runtimes_rows_match_deployed_keys(self):
        backend = _make_batch_backend()
        name = backend._format_jobdef_name('rt:latest', 1024)
        backend.batch_client.describe_job_definitions.return_value = {
            **OK, 'jobDefinitions': [{'jobDefinitionName': name, 'jobDefinitionArn': 'arn:jd', 'status': 'ACTIVE'}]
        }
        rows = backend.list_runtimes('rt:latest')
        assert rows == [('rt:latest', 1024, __version__, name)]
        rt_name, rt_memory, version, _ = rows[0]
        assert backend.get_runtime_key(rt_name, rt_memory, version) == backend.get_runtime_key('rt:latest', 1024)

    def test_delete_runtime_finds_listed_job_definition(self):
        backend = _make_batch_backend()
        name = backend._format_jobdef_name('rt:latest', 1024)
        backend.batch_client.describe_job_definitions.return_value = {
            **OK, 'jobDefinitions': [{'jobDefinitionName': name, 'jobDefinitionArn': 'arn:jd', 'status': 'ACTIVE'}]
        }
        backend.batch_client.deregister_job_definition.return_value = OK
        rt_name, rt_memory, version, _ = backend.list_runtimes()[0]
        backend.delete_runtime(rt_name, rt_memory, version)
        backend.batch_client.deregister_job_definition.assert_called_once_with(jobDefinition='arn:jd')

    def test_delete_runtime_of_missing_job_definition(self):
        backend = _make_batch_backend()
        backend.batch_client.describe_job_definitions.return_value = {**OK, 'jobDefinitions': []}
        backend.delete_runtime('rt:latest', 1024)
        backend.batch_client.deregister_job_definition.assert_not_called()

    def test_job_definitions_past_the_first_page(self):
        backend = _make_batch_backend()
        backend.batch_client, stubber = _stubbed_client('batch')
        names = [backend._format_jobdef_name(f'rt{i}:latest', 1024) for i in range(2)]
        pages = [
            {**OK, 'jobDefinitions': [{'jobDefinitionName': names[0], 'jobDefinitionArn': 'arn:jd0',
                                       'revision': 1, 'type': 'container'}], 'nextToken': 't1'},
            {**OK, 'jobDefinitions': [{'jobDefinitionName': names[1], 'jobDefinitionArn': 'arn:jd1',
                                       'revision': 1, 'type': 'container'}]},
        ]
        stubber.add_response('describe_job_definitions', pages[0], {'status': 'ACTIVE'})
        stubber.add_response('describe_job_definitions', pages[1], {'status': 'ACTIVE', 'nextToken': 't1'})
        with stubber:
            assert [row[0] for row in backend.list_runtimes()] == ['rt0:latest', 'rt1:latest']
        stubber.assert_no_pending_responses()


# ---------------------------------------------------------------------------
# AWS Lambda
# ---------------------------------------------------------------------------

def _lambda_load_config(**overrides):
    cfg = {'aws_lambda': {'execution_role': 'arn:role', 'region': REGION, **overrides}}
    lambda_config.load_config(cfg)
    return cfg['aws_lambda']


def _make_lambda_backend(**overrides):
    """Build an AWSLambdaBackend without running __init__ (which calls STS)."""
    backend = AWSLambdaBackend.__new__(AWSLambdaBackend)
    backend.name = 'aws_lambda'
    backend.region = REGION
    backend.lambda_config = _lambda_load_config(**overrides)
    backend.role_arn = 'arn:role'
    backend.namespace = None
    backend.user_key = USER_KEY
    backend.account_id = '123456789012'
    backend.package = CURRENT_PACKAGE
    backend.user_agent = 'lithops-test'
    backend.host = f'lambda.{REGION}.amazonaws.com'
    backend.credentials = Credentials('AKIDEXAMPLE', 'secret')
    backend.session = MagicMock()
    backend.lambda_client = MagicMock()
    backend.ecr_client = MagicMock()
    backend.lambda_client.create_function.return_value = {'ResponseMetadata': {'HTTPStatusCode': 201}}
    backend.lambda_client.get_function.return_value = {
        'Configuration': {'State': 'Active', 'LastUpdateStatus': 'Successful'}
    }
    return backend


def _conflict():
    return ClientError(
        {'Error': {'Code': 'ResourceConflictException', 'Message': 'Function already exist'}}, 'CreateFunction'
    )


class _TooManyAttempts(BaseException):
    """Stops a retry loop that would otherwise never end."""


class TestLambdaInvokeRetries:

    @pytest.fixture(autouse=True)
    def no_sleep(self, monkeypatch):
        monkeypatch.setattr(aws_lambda_module.time, 'sleep', lambda s: None)

    def _send(self, backend, outcomes):
        calls = []

        def send(prepared):
            calls.append(prepared.headers['Authorization'])
            if len(calls) > 100:
                raise _TooManyAttempts()
            outcome = outcomes[min(len(calls), len(outcomes)) - 1]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        backend.session.send.side_effect = send
        return calls

    @staticmethod
    def _accepted():
        return MagicMock(status_code=202, headers={'x-amzn-RequestId': 'req-1'})

    @pytest.mark.parametrize('error', [
        EndpointConnectionError(endpoint_url='u'),
        ConnectTimeoutError(endpoint_url='u'),
    ])
    def test_gives_up_after_last_attempt(self, error):
        backend = _make_lambda_backend()
        calls = self._send(backend, [error])
        with pytest.raises(type(error)):
            backend.invoke('rt', 256, {'a': 1})
        assert len(calls) == aws_lambda_module.INVOKE_RETRIES

    def test_resigns_each_attempt(self, monkeypatch):
        backend = _make_lambda_backend()
        add_auth = MagicMock(side_effect=lambda request: request.headers.__setitem__('Authorization', 'sig'))
        monkeypatch.setattr(aws_lambda_module, 'SigV4Auth', MagicMock(return_value=MagicMock(add_auth=add_auth)))
        error = EndpointConnectionError(endpoint_url='u')
        calls = self._send(backend, [error, error, self._accepted()])
        assert backend.invoke('rt', 256, {'a': 1}) == 'req-1'
        assert len(calls) == 3
        assert add_auth.call_count == 3

    def test_read_timeout_is_not_resent(self):
        backend = _make_lambda_backend()
        calls = self._send(backend, [ReadTimeoutError(endpoint_url='u'), self._accepted()])
        with pytest.raises(ReadTimeoutError):
            backend.invoke('rt', 256, {'a': 1})
        assert len(calls) == 1


class TestLambdaRuntimeUpdate:

    def test_default_runtime_updates_existing_function(self, monkeypatch):
        backend = _make_lambda_backend(env_vars={'A': 'b'})
        monkeypatch.setattr(backend, '_get_layer', lambda runtime_name: 'arn:layer')
        monkeypatch.setattr(backend, '_create_handler_bin', lambda: b'zip')
        backend.lambda_client.create_function.side_effect = _conflict()

        backend._deploy_default_runtime('default-runtime-v311', 256, 600)

        function_name = backend._format_function_name('default-runtime-v311', 256)
        backend.lambda_client.update_function_code.assert_called_once_with(FunctionName=function_name, ZipFile=b'zip')
        conf = backend.lambda_client.update_function_configuration.call_args.kwargs
        assert conf['FunctionName'] == function_name
        assert conf['Timeout'] == 600
        assert conf['MemorySize'] == 256
        assert conf['Layers'] == ['arn:layer']
        assert conf['Environment'] == {'Variables': {'A': 'b'}}

    def test_container_runtime_is_looked_up_by_its_tag(self):
        """A plain describe_images stops at 100, so the tag can be on a later page"""
        backend = _make_lambda_backend()
        backend.ecr_client.describe_images.return_value = {
            'imageDetails': [{'imageDigest': 'sha256:new'}]
        }
        backend._deploy_container_runtime('myrt:v2', 1024, 300)
        backend.ecr_client.describe_images.assert_called_once_with(
            repositoryName=backend._format_repo_name('myrt'),
            imageIds=[{'imageTag': 'v2'}],
        )
        code = backend.lambda_client.create_function.call_args.kwargs
        assert code['Code']['ImageUri'].endswith('@sha256:new')

    def test_container_runtime_updates_existing_function(self):
        backend = _make_lambda_backend()
        backend.ecr_client.describe_images.return_value = {
            'imageDetails': [{'imageTags': ['v2'], 'imageDigest': 'sha256:new'}]
        }
        backend.lambda_client.create_function.side_effect = _conflict()

        backend._deploy_container_runtime('myrt:v2', 1024, 300)

        code = backend.lambda_client.update_function_code.call_args.kwargs
        assert code['ImageUri'].endswith('@sha256:new')
        assert code['Architectures'] == ['x86_64']
        conf = backend.lambda_client.update_function_configuration.call_args.kwargs
        assert conf['Timeout'] == 300
        assert 'Architectures' not in conf and 'PackageType' not in conf

    def test_waits_for_update_before_configuring(self, monkeypatch):
        monkeypatch.setattr(aws_lambda_module.time, 'sleep', lambda s: None)
        backend = _make_lambda_backend()
        backend.ecr_client.describe_images.return_value = {
            'imageDetails': [{'imageTags': ['latest'], 'imageDigest': 'sha256:new'}]
        }
        backend.lambda_client.create_function.side_effect = _conflict()
        events = []
        statuses = iter(['Successful', 'InProgress', 'Successful', 'Successful'])

        def get_function(FunctionName):
            status = next(statuses)
            events.append(f'get:{status}')
            return {'Configuration': {'State': 'Active', 'LastUpdateStatus': status}}

        backend.lambda_client.get_function.side_effect = get_function
        backend.lambda_client.update_function_code.side_effect = lambda **kw: events.append('code')
        def update_configuration(**kw):
            events.append('config')
            return {'FunctionArn': 'arn:fn'}

        backend.lambda_client.update_function_configuration.side_effect = update_configuration
        backend._deploy_container_runtime('myrt', 1024, 300)
        assert events == ['get:Successful', 'code', 'get:InProgress', 'get:Successful', 'config', 'get:Successful']

    def test_failed_update_raises(self):
        backend = _make_lambda_backend()
        backend.lambda_client.get_function.return_value = {
            'Configuration': {'State': 'Active', 'LastUpdateStatus': 'Failed'}
        }
        with pytest.raises(Exception, match='not updated'):
            backend._wait_for_function_deployed('fn')


class TestLambdaEnvVarsAndUserTags:

    @pytest.mark.parametrize('key', ['env_vars', 'user_tags'])
    @pytest.mark.parametrize('value', [
        {'A': 'b', 'N': 1},
        [{'name': 'A', 'value': 'b'}, {'name': 'N', 'value': 1}],
    ])
    def test_dict_and_list_forms_are_accepted(self, key, value):
        assert _lambda_load_config(**{key: value})[key] == {'A': 'b', 'N': '1'}

    @pytest.mark.parametrize('key', ['env_vars', 'user_tags'])
    def test_empty_values(self, key):
        assert _lambda_load_config()[key] == {}
        assert _lambda_load_config(**{key: None})[key] == {}

    @pytest.mark.parametrize('key', ['env_vars', 'user_tags'])
    @pytest.mark.parametrize('value', ['A=b', [{'name': 'A'}], ['A']])
    def test_invalid_forms_are_rejected(self, key, value):
        with pytest.raises(Exception, match=key):
            _lambda_load_config(**{key: value})

    @pytest.mark.parametrize('env_vars', [{'A': 'b'}, [{'name': 'A', 'value': 'b'}]])
    @pytest.mark.parametrize('user_tags', [{'team': 'x'}, [{'name': 'team', 'value': 'x'}]])
    def test_container_runtime_receives_both(self, env_vars, user_tags):
        backend = _make_lambda_backend(env_vars=env_vars, user_tags=user_tags)
        backend.ecr_client.describe_images.return_value = {
            'imageDetails': [{'imageTags': ['latest'], 'imageDigest': 'sha256:abc'}]
        }
        backend._deploy_container_runtime('myrt', 1024, 300)
        kwargs = backend.lambda_client.create_function.call_args.kwargs
        assert kwargs['Environment'] == {'Variables': {'A': 'b'}}
        assert kwargs['Tags'] == {'runtime_name': 'myrt', 'lithops_version': __version__, 'team': 'x'}

    @pytest.mark.parametrize('env_vars', [{'A': 'b'}, [{'name': 'A', 'value': 'b'}]])
    def test_default_runtime_receives_env_vars(self, env_vars, monkeypatch):
        backend = _make_lambda_backend(env_vars=env_vars)
        monkeypatch.setattr(backend, '_get_layer', lambda runtime_name: 'arn:layer')
        monkeypatch.setattr(backend, '_create_handler_bin', lambda: b'zip')
        backend._deploy_default_runtime('default-runtime-v311', 256, 600)
        kwargs = backend.lambda_client.create_function.call_args.kwargs
        assert kwargs['Environment'] == {'Variables': {'A': 'b'}}


class TestLambdaLayerDeletion:

    def test_paginated_layer_versions_are_all_deleted(self):
        backend = _make_lambda_backend()
        backend.lambda_client, stubber = _stubbed_client('lambda')
        stubber.add_response(
            'list_layer_versions', {'LayerVersions': [{'Version': 51}], 'NextMarker': 'm1'}, {'LayerName': 'ly'}
        )
        stubber.add_response(
            'list_layer_versions', {'LayerVersions': [{'Version': 1}]}, {'LayerName': 'ly', 'Marker': 'm1'}
        )
        deleted = {'ResponseMetadata': {'HTTPStatusCode': 204}}
        stubber.add_response('delete_layer_version', deleted, {'LayerName': 'ly', 'VersionNumber': 51})
        stubber.add_response('delete_layer_version', deleted, {'LayerName': 'ly', 'VersionNumber': 1})
        with stubber:
            backend._delete_layer('ly')
        stubber.assert_no_pending_responses()

    def test_layers_past_the_first_page_are_listed(self):
        backend = _make_lambda_backend()
        backend.lambda_client, stubber = _stubbed_client('lambda')

        def layer(name):
            arn = f'arn:aws:lambda:{REGION}:123456789012:layer:{name}:1'
            return {'LayerName': name, 'LatestMatchingVersion': {'LayerVersionArn': arn}}

        names = [f'lithops_v3_{USER_KEY}_{i}' for i in range(2)]
        stubber.add_response('list_layers', {'Layers': [layer(names[0]), layer('other')], 'NextMarker': 'm1'}, {})
        stubber.add_response('list_layers', {'Layers': [layer(names[1])]}, {'Marker': 'm1'})
        with stubber:
            assert [name for name, _ in backend._list_layers()] == names
        stubber.assert_no_pending_responses()


class TestLambdaRuntimeListing:

    @staticmethod
    def _function(name):
        arn = f'arn:aws:lambda:{REGION}:123456789012:function:{name}'
        return {'FunctionName': name, 'MemorySize': 256, 'FunctionArn': arn}

    def test_functions_past_the_first_page_are_listed(self):
        backend = _make_lambda_backend()
        backend.lambda_client, stubber = _stubbed_client('lambda')
        names = [f'lithops-worker-{USER_KEY}-{i}' for i in range(2)]
        pages = [
            ({'Functions': [self._function(names[0]), self._function('other')], 'NextMarker': 'm1'}, {}),
            ({'Functions': [self._function(names[1])]}, {'Marker': 'm1'}),
        ]
        for i, (page, params) in enumerate(pages):
            stubber.add_response('list_functions', page, params)
            stubber.add_response(
                'list_tags', {'Tags': {'runtime_name': f'rt{i}', 'lithops_version': __version__}},
                {'Resource': self._function(names[i])['FunctionArn']}
            )
        with stubber:
            rows = backend.list_runtimes()
        stubber.assert_no_pending_responses()
        assert rows == [(f'rt{i}', 256, __version__, name) for i, name in enumerate(names)]

    def test_clean_deletes_functions_past_the_first_page(self, monkeypatch):
        backend = _make_lambda_backend()
        backend.lambda_client, stubber = _stubbed_client('lambda')
        monkeypatch.setattr(backend, '_list_layers', lambda: [])
        names = [f'lithops-worker-{USER_KEY}-{i}' for i in range(2)]
        deleted = {'ResponseMetadata': {'HTTPStatusCode': 204}}
        stubber.add_response('list_functions', {'Functions': [self._function(names[0])], 'NextMarker': 'm1'}, {})
        stubber.add_response('delete_function', deleted, {'FunctionName': names[0]})
        stubber.add_response('list_functions', {'Functions': [self._function(names[1])]}, {'Marker': 'm1'})
        stubber.add_response('delete_function', deleted, {'FunctionName': names[1]})
        with stubber:
            backend.clean()
        stubber.assert_no_pending_responses()

    def test_delete_runtime_of_missing_function(self, monkeypatch):
        backend = _make_lambda_backend()
        backend.lambda_client.delete_function.side_effect = ClientError(
            {'Error': {'Code': 'ResourceNotFoundException', 'Message': 'Function not found'}}, 'DeleteFunction'
        )
        delete_layer = MagicMock()
        monkeypatch.setattr(backend, '_delete_layer', delete_layer)
        backend.delete_runtime(backend._get_default_runtime_name(), 256)
        delete_layer.assert_called_once()

    def test_delete_function_raises_other_errors(self):
        backend = _make_lambda_backend()
        backend.lambda_client.delete_function.side_effect = ClientError(
            {'Error': {'Code': 'AccessDeniedException', 'Message': 'denied'}}, 'DeleteFunction'
        )
        with pytest.raises(ClientError):
            backend._delete_function('fn')


class TestLambdaTags:

    USER_TAGS = {'team': 'x'}

    def _expected(self, runtime_name):
        return {'runtime_name': runtime_name, 'lithops_version': __version__, **self.USER_TAGS}

    @pytest.fixture
    def default_backend(self, monkeypatch):
        backend = _make_lambda_backend(user_tags=self.USER_TAGS)
        monkeypatch.setattr(backend, '_get_layer', lambda runtime_name: 'arn:layer')
        monkeypatch.setattr(backend, '_create_handler_bin', lambda: b'zip')
        return backend

    def test_default_runtime_is_created_with_user_tags(self, default_backend):
        default_backend._deploy_default_runtime('default-runtime-v311', 256, 600)
        tags = default_backend.lambda_client.create_function.call_args.kwargs['Tags']
        assert tags == self._expected('default-runtime-v311')

    def test_default_runtime_update_sets_tags(self, default_backend):
        client = default_backend.lambda_client
        client.create_function.side_effect = _conflict()
        client.update_function_configuration.return_value = {'FunctionArn': 'arn:fn'}
        default_backend._deploy_default_runtime('default-runtime-v311', 256, 600)
        client.tag_resource.assert_called_once_with(Resource='arn:fn', Tags=self._expected('default-runtime-v311'))
        client.untag_resource.assert_not_called()

    def test_container_runtime_update_sets_tags(self):
        backend = _make_lambda_backend(user_tags=self.USER_TAGS)
        backend.ecr_client.describe_images.return_value = {
            'imageDetails': [{'imageTags': ['latest'], 'imageDigest': 'sha256:abc'}]
        }
        backend.lambda_client.create_function.side_effect = _conflict()
        backend.lambda_client.update_function_configuration.return_value = {'FunctionArn': 'arn:fn'}
        backend._deploy_container_runtime('myrt', 1024, 300)
        backend.lambda_client.tag_resource.assert_called_once_with(Resource='arn:fn', Tags=self._expected('myrt'))
