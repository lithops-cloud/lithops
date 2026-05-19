#
# Unit tests for the Kubernetes backend internals. No live cluster required;
# the kube API is mocked. Covers config validation, security context injection,
# and runtime architecture resolution (auto-detect + override).
#

import copy
from unittest.mock import MagicMock

import pytest
import yaml
from kubernetes.client.rest import ApiException

from lithops.serverless.backends.k8s import config as k8s_config
from lithops.serverless.backends.k8s.k8s import KubernetesBackend


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
