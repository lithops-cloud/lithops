#
# Unit tests for the Kubernetes backend internals. No live cluster required;
# the kube API is mocked. Covers config validation, security context injection,
# runtime architecture resolution (auto-detect + override) and the Job resources
# the backend creates.
#

import base64
import copy
import json
from unittest.mock import MagicMock

import pytest
import yaml
from kubernetes.client.rest import ApiException

from lithops.serverless.backends.k8s import config as k8s_config
from lithops.serverless.backends.k8s.k8s import KubernetesBackend


def test_memory_is_compared_in_megabytes():
    """Mi used to be multiplied by 1024 and then labelled M, so 512Mi was not 512"""
    backend = _make_backend()
    assert backend.convert_memory_units(512, 'Mi') == (512, 'M')
    assert backend.convert_memory_units(512, 'M') == (512, 'M')
    assert backend.convert_memory_units(16384, 'Ki') == (16, 'M')
    assert backend.convert_memory_units(2, 'Gi') == (2048, 'M')
    assert backend.convert_memory_units(2, 'G') == (2000, 'M')


def _make_backend(overrides=None):
    """Build a KubernetesBackend without running __init__ (which needs a cluster)."""
    backend = KubernetesBackend.__new__(KubernetesBackend)
    backend.k8s_config = dict(overrides or {})
    backend.core_api = MagicMock()
    return backend


def _node(arch):
    node = MagicMock()
    node.status.node_info.architecture = arch
    return node


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------

class TestRegistrySecret:

    def test_docker_config_uses_the_keys_kubernetes_reads(self):
        backend = _make_backend({
            'docker_user': 'me',
            'docker_password': 'pw',
            'docker_server': 'registry.example',
        })
        backend.namespace = 'ns'
        backend.core_api.delete_namespaced_secret.side_effect = ApiException(status=404)
        backend._create_container_registry_secret()
        secret = backend.core_api.create_namespaced_secret.call_args.args[1]
        payload = json.loads(base64.b64decode(secret.data['.dockerconfigjson']))
        auth = payload['auths']['registry.example']
        assert auth['username'] == 'me'
        assert auth['password'] == 'pw'
        assert auth['auth'] == base64.b64encode(b'me:pw').decode()
        assert 'Username' not in auth


class TestLoadConfig:

    def test_defaults_applied(self):
        cfg = {'k8s': {}}
        k8s_config.load_config(cfg)
        for key, value in k8s_config.DEFAULT_CONFIG_KEYS.items():
            assert cfg['k8s'][key] == value
        assert cfg['k8s']['container_security_context'] == k8s_config.DEFAULT_CONTAINER_SECURITY_CONTEXT
        assert cfg['k8s']['pod_security_context'] is None

    def test_user_security_context_replaces_default(self):
        custom = {'capabilities': {'add': ['NET_BIND_SERVICE']}}
        cfg = {'k8s': {'container_security_context': custom}}
        k8s_config.load_config(cfg)
        assert cfg['k8s']['container_security_context'] == custom

    def test_security_context_can_be_disabled(self):
        cfg = {'k8s': {'container_security_context': None}}
        k8s_config.load_config(cfg)
        assert cfg['k8s']['container_security_context'] is None

    @pytest.mark.parametrize('key', ['container_security_context', 'pod_security_context'])
    def test_security_context_must_be_mapping_or_null(self, key):
        cfg = {'k8s': {key: 'not-a-dict'}}
        with pytest.raises(Exception, match=key):
            k8s_config.load_config(cfg)

    @pytest.mark.parametrize('arch', ['amd64', 'arm64', None])
    def test_runtime_arch_accepts_supported_values(self, arch):
        cfg = {'k8s': {'runtime_arch': arch}}
        k8s_config.load_config(cfg)
        assert cfg['k8s']['runtime_arch'] == arch

    @pytest.mark.parametrize('arch', ['ppc64le', 'x86_64', 'AMD64', ''])
    def test_runtime_arch_rejects_unsupported_values(self, arch):
        cfg = {'k8s': {'runtime_arch': arch}}
        with pytest.raises(Exception, match='runtime_arch'):
            k8s_config.load_config(cfg)


# ---------------------------------------------------------------------------
# _apply_security_context
# ---------------------------------------------------------------------------

class TestApplySecurityContext:

    def _fresh_job(self):
        return yaml.safe_load(k8s_config.JOB_DEFAULT)

    def test_no_context_no_modification(self):
        backend = _make_backend({'pod_security_context': None, 'container_security_context': None})
        job = self._fresh_job()
        before = copy.deepcopy(job['spec']['template']['spec'])
        backend._apply_security_context(job)
        assert job['spec']['template']['spec'] == before

    def test_container_context_injected(self):
        sc = {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}}
        backend = _make_backend({'pod_security_context': None, 'container_security_context': sc})
        job = self._fresh_job()
        backend._apply_security_context(job)
        assert job['spec']['template']['spec']['containers'][0]['securityContext'] == sc
        assert 'securityContext' not in job['spec']['template']['spec']

    def test_pod_context_injected(self):
        sc = {'runAsNonRoot': True, 'runAsUser': 1000}
        backend = _make_backend({'pod_security_context': sc, 'container_security_context': None})
        job = self._fresh_job()
        backend._apply_security_context(job)
        assert job['spec']['template']['spec']['securityContext'] == sc
        assert 'securityContext' not in job['spec']['template']['spec']['containers'][0]

    def test_both_contexts_injected(self):
        pod_sc = {'runAsNonRoot': True, 'runAsUser': 1000}
        ctr_sc = {'allowPrivilegeEscalation': False}
        backend = _make_backend({'pod_security_context': pod_sc, 'container_security_context': ctr_sc})
        job = self._fresh_job()
        backend._apply_security_context(job)
        assert job['spec']['template']['spec']['securityContext'] == pod_sc
        assert job['spec']['template']['spec']['containers'][0]['securityContext'] == ctr_sc


# ---------------------------------------------------------------------------
# _detect_cluster_arch
# ---------------------------------------------------------------------------

class TestDetectClusterArch:

    def test_homogeneous_cluster_returns_arch(self):
        backend = _make_backend()
        backend.core_api.list_node.return_value.items = [_node('arm64'), _node('arm64')]
        assert backend._detect_cluster_arch() == 'arm64'

    def test_mixed_cluster_returns_none(self):
        backend = _make_backend()
        backend.core_api.list_node.return_value.items = [_node('amd64'), _node('arm64')]
        assert backend._detect_cluster_arch() is None

    def test_empty_cluster_returns_none(self):
        backend = _make_backend()
        backend.core_api.list_node.return_value.items = []
        assert backend._detect_cluster_arch() is None

    def test_api_failure_returns_none(self):
        backend = _make_backend()
        backend.core_api.list_node.side_effect = ApiException(status=403, reason='Forbidden')
        assert backend._detect_cluster_arch() is None


# ---------------------------------------------------------------------------
# _resolve_runtime_arch
# ---------------------------------------------------------------------------

class TestResolveRuntimeArch:

    def test_configured_value_wins_over_auto_detect(self):
        backend = _make_backend({'runtime_arch': 'amd64'})
        backend.core_api.list_node.return_value.items = [_node('arm64')]
        assert backend._resolve_runtime_arch() == 'amd64'
        backend.core_api.list_node.assert_not_called()

    def test_auto_detect_used_when_unconfigured(self):
        backend = _make_backend({'runtime_arch': None})
        backend.core_api.list_node.return_value.items = [_node('arm64')]
        assert backend._resolve_runtime_arch() == 'arm64'

    def test_fallback_to_default_when_mixed_cluster(self):
        backend = _make_backend({'runtime_arch': None})
        backend.core_api.list_node.return_value.items = [_node('amd64'), _node('arm64')]
        assert backend._resolve_runtime_arch() == k8s_config.DEFAULT_RUNTIME_ARCH

    def test_fallback_to_default_when_api_fails(self):
        backend = _make_backend({'runtime_arch': None})
        backend.core_api.list_node.side_effect = ApiException(status=500, reason='boom')
        assert backend._resolve_runtime_arch() == k8s_config.DEFAULT_RUNTIME_ARCH

    def test_unsupported_detected_arch_falls_back(self):
        backend = _make_backend({'runtime_arch': None})
        backend.core_api.list_node.return_value.items = [_node('ppc64le')]
        assert backend._resolve_runtime_arch() == k8s_config.DEFAULT_RUNTIME_ARCH


# ---------------------------------------------------------------------------
# Waiting for the metadata job and the master pod
# ---------------------------------------------------------------------------

def _pod(phase='Pending', waiting_reason=None):
    pod = MagicMock()
    pod.status.phase = phase
    pod.status.reason = None
    pod.status.pod_ip = '10.0.0.1'
    if waiting_reason:
        status = MagicMock()
        status.state.waiting.reason = waiting_reason
        status.state.waiting.message = 'pull access denied'
        pod.status.container_statuses = [status]
    else:
        pod.status.container_statuses = []
    return pod


def _job(succeeded=None, failed=None, conditions=()):
    job = MagicMock()
    job.status.succeeded = succeeded
    job.status.failed = failed
    job.status.conditions = list(conditions)
    return job


def _condition(type_, reason):
    condition = MagicMock()
    condition.type, condition.status = type_, 'True'
    condition.reason, condition.message = reason, 'Job was active longer than specified deadline'
    return condition


def _meta_backend():
    backend = _make_backend({'master_timeout': 600})
    backend.batch_api = MagicMock()
    backend.namespace = 'default'
    backend.user = 'u'
    backend.internal_storage = MagicMock()
    backend.internal_storage.storage.config = {}
    return backend


class TestMetadataJobWait:
    """The metadata wait ends when the job cannot succeed, instead of hanging"""

    def test_a_pod_that_cannot_pull_its_image_fails_at_once(self, monkeypatch):
        backend = _meta_backend()
        watcher = MagicMock()
        watcher.stream.return_value = iter([{'object': _job()}])
        monkeypatch.setattr('lithops.serverless.backends.k8s.k8s.watch.Watch', lambda: watcher)
        backend.core_api.list_namespaced_pod.return_value.items = [_pod(waiting_reason='ImagePullBackOff')]
        with pytest.raises(Exception, match='ImagePullBackOff'):
            backend._generate_runtime_meta('docker.io/me/runtime:1')

    def test_a_job_past_its_deadline_fails(self, monkeypatch):
        backend = _meta_backend()
        watcher = MagicMock()
        failed_job = _job(conditions=[_condition('Failed', 'DeadlineExceeded')])
        watcher.stream.return_value = iter([{'object': failed_job}])
        monkeypatch.setattr('lithops.serverless.backends.k8s.k8s.watch.Watch', lambda: watcher)
        with pytest.raises(Exception, match='DeadlineExceeded'):
            backend._generate_runtime_meta('docker.io/me/runtime:1')


class TestMasterPodWait:

    def _wait(self, monkeypatch, events):
        backend = _meta_backend()
        backend.master_name = 'lithops-master-u'
        backend.core_api.list_namespaced_pod.return_value.items = []
        watcher = MagicMock()
        watcher.stream.return_value = iter(events)
        monkeypatch.setattr('lithops.serverless.backends.k8s.k8s.watch.Watch', lambda: watcher)
        monkeypatch.setattr('lithops.serverless.backends.k8s.k8s.time.sleep', lambda s: None)
        return backend._start_master('docker.io/me/runtime:1'), watcher

    def test_returns_the_ip_of_the_running_master(self, monkeypatch):
        ip, watcher = self._wait(monkeypatch, [{'object': _pod()}, {'object': _pod('Running')}])
        assert ip == '10.0.0.1'
        assert watcher.stream.call_args.kwargs['timeout_seconds'] == 600

    def test_a_master_that_cannot_pull_its_image_fails(self, monkeypatch):
        with pytest.raises(Exception, match='master pod did not start: ErrImagePull'):
            self._wait(monkeypatch, [{'object': _pod(waiting_reason='ErrImagePull')}])

    def test_a_master_not_running_in_time_fails(self, monkeypatch):
        with pytest.raises(Exception, match='not running after 600 seconds'):
            self._wait(monkeypatch, [{'object': _pod()}])


# ---------------------------------------------------------------------------
# Job resources of the master, the workers and the metadata extraction. They
# were captured before the three builders were folded into _job_resource and are
# compared key order included, so the resources sent to the cluster stay the same
# ---------------------------------------------------------------------------

_JOB_CASES = {
    # No registry credentials and no security contexts
    'plain': (
        {'pod_security_context': None, 'container_security_context': None},
        'docker.io/me/runtime:latest',
    ),
    # Registry credentials and both security contexts
    'secured': (
        {
            'docker_user': 'me', 'docker_password': 'pw', 'docker_server': 'docker.io',
            'pod_security_context': {'runAsNonRoot': True, 'runAsUser': 1000},
            'container_security_context': {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}},
        },
        'docker.io/me/runtime:1',
    ),
}


def _job_backend(case):
    cfg, image = _JOB_CASES[case]
    backend = _make_backend(dict(cfg, master_timeout=600, runtime_timeout=300, runtime_cpu=1))
    backend.core_api.list_namespaced_pod.return_value.items = []
    backend.batch_api = MagicMock()
    backend.namespace = 'lithops-ns'
    backend.user = 'u1'
    backend.master_name = 'lithops-master-u1'
    backend.rabbitmq_executor = False
    backend.jobs = []
    backend.internal_storage = MagicMock()
    backend.internal_storage.storage.config = {'backend': 'localhost'}
    backend.internal_storage.get_data.return_value = b'{"preinstalls": []}'
    backend._format_job_name = lambda *args, **kwargs: 'lithops-worker-999-abc'
    return backend, image


def _created_job(backend):
    return backend.batch_api.create_namespaced_job.call_args.kwargs['body']


class TestJobResources:
    """The three Job resources share their common parts, and keep their own"""

    @pytest.fixture(autouse=True)
    def _no_sleep(self, monkeypatch):
        monkeypatch.setattr('lithops.serverless.backends.k8s.k8s.time.sleep', lambda s: None)

    def _watch(self, monkeypatch, obj):
        watcher = MagicMock()
        watcher.stream.return_value = iter([{'object': obj}])
        monkeypatch.setattr('lithops.serverless.backends.k8s.k8s.watch.Watch', lambda: watcher)

    @staticmethod
    def _common(job, case, image, name):
        pod_spec = job['spec']['template']['spec']
        container = pod_spec['containers'][0]
        assert job['metadata']['name'] == name
        assert job['metadata']['namespace'] == 'lithops-ns'
        assert job['metadata']['labels']['user'] == 'u1'
        assert container['image'] == image
        cfg = _JOB_CASES[case][0]
        assert ('imagePullSecrets' in pod_spec) == ('docker_password' in cfg)
        assert pod_spec.get('securityContext') == cfg['pod_security_context']
        assert container.get('securityContext') == cfg['container_security_context']
        return container

    @pytest.mark.parametrize('case', ['plain', 'secured'])
    def test_master_job(self, monkeypatch, case):
        backend, image = _job_backend(case)
        self._watch(monkeypatch, _pod('Running'))
        backend._start_master(image)
        job = _created_job(backend)
        container = self._common(job, case, image, 'lithops-master-u1')
        assert job['spec']['activeDeadlineSeconds'] == 600
        assert container['env'][0]['value'] == 'run_master'

    @pytest.mark.parametrize('case', ['plain', 'secured'])
    def test_worker_job(self, case):
        backend, image = _job_backend(case)
        backend._start_master = lambda image: '10.0.0.1'
        payload = {
            'job_key': 'A1B2-000', 'executor_id': 'a1b2', 'job_id': '000',
            'max_workers': 4, 'total_calls': 10, 'chunksize': 3,
        }
        assert backend.invoke(image, 1024, payload) == 'lithops-a1b2-000'
        job = _created_job(backend)
        container = self._common(job, case, image, 'lithops-a1b2-000')
        assert job['spec']['activeDeadlineSeconds'] == 300
        assert job['spec']['parallelism'] == 4
        assert container['env'][0]['value'] == 'run_job'
        assert container['env'][2]['value'] == '10.0.0.1'
        assert container['resources']['limits'] == {'memory': '1024Mi', 'cpu': '1'}
        # Only a tag other than latest is pulled once and reused
        assert container.get('imagePullPolicy') == (None if image.endswith(':latest') else 'IfNotPresent')

    @pytest.mark.parametrize('case', ['plain', 'secured'])
    def test_metadata_job(self, monkeypatch, case):
        backend, image = _job_backend(case)
        self._watch(monkeypatch, _job(succeeded=1))
        assert backend._generate_runtime_meta(image) == {'preinstalls': []}
        job = _created_job(backend)
        container = self._common(job, case, image, 'lithops-worker-999-abc-meta')
        assert container['imagePullPolicy'] == 'Always'
        assert container['env'][0]['value'] == 'get_metadata'

