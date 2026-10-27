#
# Unit tests for the Knative backend internals. No live cluster required;
# the kube API and the HTTP requests are mocked.
#

from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.rest import ApiException

from lithops.serverless.backends.knative import config as kn_config
from lithops.serverless.backends.knative import knative
from lithops.serverless.backends.knative.knative import KnativeServingBackend


def _make_backend(overrides=None, incluster=False):
    """Build a KnativeServingBackend without running __init__ (which needs a cluster)."""
    backend = KnativeServingBackend.__new__(KnativeServingBackend)
    backend.name = 'knative'
    backend.kn_config = {**kn_config.DEFAULT_CONFIG_KEYS, **(overrides or {})}
    backend.namespace = 'lithops'
    backend.cluster = 'kind-test'
    backend.networking_layer = backend.kn_config['networking_layer']
    backend.ingress_endpoint = backend.kn_config.get('ingress_endpoint')
    backend.is_incluster = incluster
    backend.core_api = MagicMock()
    backend.custom_api = MagicMock()
    backend._service_urls = {}
    return backend


def _service(generation=1, observed=1, ready='True', created='rev-2', latest_ready='rev-2', url=None):
    status = {
        'observedGeneration': observed,
        'latestCreatedRevisionName': created,
        'latestReadyRevisionName': latest_ready,
        'url': url or 'http://svc.lithops.example.com',
        'conditions': [
            {'type': 'ConfigurationsReady', 'status': 'True'},
            {'type': 'Ready', 'status': ready, 'reason': 'RevisionFailed', 'message': 'image not found'},
        ],
    }
    return {'metadata': {'generation': generation, 'resourceVersion': '7'}, 'status': status}


def _response(status_code, body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {}
    resp.text = 'error body'
    return resp


class TestLoadConfig:

    def test_defaults_applied(self):
        cfg = {'knative': {}}
        kn_config.load_config(cfg)
        for key, value in kn_config.DEFAULT_CONFIG_KEYS.items():
            assert cfg['knative'][key] == value
        assert cfg['knative']['invoke_pool_threads'] == cfg['knative']['max_workers']

    @pytest.mark.parametrize('layer', ['kourier', 'istio', 'contour'])
    def test_networking_layers(self, layer):
        cfg = {'knative': {'networking_layer': layer}}
        kn_config.load_config(cfg)
        assert cfg['knative']['networking_layer'] == layer

    def test_unknown_networking_layer_rejected(self):
        with pytest.raises(Exception, match='networking_layer'):
            kn_config.load_config({'knative': {'networking_layer': 'nginx'}})

    def test_unsupported_runtime_arch_rejected(self):
        with pytest.raises(Exception, match='runtime_arch'):
            kn_config.load_config({'knative': {'runtime_arch': 'x86_64'}})

    def test_runtime_prefixed_with_registry(self):
        cfg = {'knative': {'runtime': 'user/image:1', 'docker_server': 'quay.io'}}
        kn_config.load_config(cfg)
        assert cfg['knative']['runtime'] == 'quay.io/user/image:1'


class TestServiceResource:

    def test_fields(self):
        backend = _make_backend({'runtime_cpu': 2, 'max_workers': 30})
        svc = backend._service_resource('svc-name', 'docker.io/user/img:1', 1024, 300)

        assert svc['apiVersion'] == 'serving.knative.dev/v1'
        assert svc['metadata']['name'] == 'svc-name'
        assert svc['metadata']['namespace'] == 'lithops'
        template = svc['spec']['template']
        assert template['metadata']['labels']['type'] == 'lithops-runtime'
        annotations = template['metadata']['annotations']
        assert annotations['autoscaling.knative.dev/min-scale'] == '0'
        assert annotations['autoscaling.knative.dev/max-scale'] == '30'
        assert annotations['autoscaling.knative.dev/target-utilization-percentage'] == '100'
        assert 'client.knative.dev/updateTimestamp' in annotations
        spec = template['spec']
        assert spec['containerConcurrency'] == 1
        assert spec['timeoutSeconds'] == 300
        assert spec['responseStartTimeoutSeconds'] == 300
        container = spec['containers'][0]
        assert container['image'] == 'docker.io/user/img:1'
        assert container['resources']['limits'] == {'memory': '1024Mi', 'cpu': '2'}
        assert container['resources']['requests'] == {'memory': '1024Mi', 'cpu': '2'}
        assert {'name': 'TIMEOUT', 'value': '300'} in container['env']
        assert 'imagePullSecrets' not in spec

    def test_pull_secret_with_registry_credentials(self):
        backend = _make_backend({'docker_user': 'u', 'docker_password': 'p'})
        svc = backend._service_resource('svc-name', 'img', 512, 600)
        assert svc['spec']['template']['spec']['imagePullSecrets'] == [{'name': knative.REGISTRY_SECRET}]


class TestServiceState:

    def test_ready(self):
        assert knative._service_state(_service())[0] == 'ready'

    def test_failed_reports_reason(self):
        state, message = knative._service_state(_service(ready='False'))
        assert state == 'failed'
        assert 'RevisionFailed' in message and 'image not found' in message

    @pytest.mark.parametrize('service', [
        _service(generation=2, observed=1),      # spec not seen by the controller yet
        _service(ready='Unknown'),
        _service(created='rev-3', latest_ready='rev-2'),
    ])
    def test_pending(self, service):
        assert knative._service_state(service)[0] == 'pending'

    def test_no_conditions_is_pending(self):
        assert knative._service_state({'metadata': {'generation': 1}, 'status': {}})[0] == 'pending'


class TestCreateService:

    def test_create(self):
        backend = _make_backend()
        backend.custom_api.get_namespaced_custom_object.return_value = _service()
        backend._create_service('img', 512, 600)
        backend.custom_api.create_namespaced_custom_object.assert_called_once()
        backend.custom_api.replace_namespaced_custom_object.assert_not_called()

    def test_existing_service_is_patched(self):
        backend = _make_backend()
        backend.custom_api.create_namespaced_custom_object.side_effect = ApiException(status=409)
        backend.custom_api.get_namespaced_custom_object.return_value = _service()
        backend._create_service('img', 512, 600)
        body = backend.custom_api.patch_namespaced_custom_object.call_args.kwargs['body']
        # Only what Lithops sets: Knative rejects losing its own annotations
        assert set(body) == {'metadata', 'spec'}
        assert set(body['metadata']) == {'labels'}
        assert body['spec']['template']['spec']['containers'][0]['image'] == 'img'

    def test_rejection_reports_webhook_message(self):
        backend = _make_backend()
        error = ApiException(status=400)
        error.body = '{"message": "expected 0 <= 900 <= 600: spec.template.spec.timeoutSeconds"}'
        backend.custom_api.create_namespaced_custom_object.side_effect = error
        with pytest.raises(Exception, match='expected 0 <= 900 <= 600'):
            backend._create_service('img', 512, 900)

    def test_failed_revision_raises(self):
        backend = _make_backend()
        backend.custom_api.get_namespaced_custom_object.return_value = _service(ready='False')
        with pytest.raises(Exception, match='image not found'):
            backend._create_service('img', 512, 600)

    def test_image_pull_error_raises(self):
        backend = _make_backend()
        backend.custom_api.get_namespaced_custom_object.return_value = _service(ready='Unknown')
        pod = MagicMock()
        pod.status.container_statuses = [MagicMock()]
        pod.status.container_statuses[0].state.waiting.reason = 'ImagePullBackOff'
        pod.status.container_statuses[0].state.waiting.message = 'manifest unknown'
        backend.core_api.list_namespaced_pod.return_value.items = [pod]
        with pytest.raises(Exception, match='ImagePullBackOff: manifest unknown'):
            backend._create_service('img', 512, 600)
        assert backend.core_api.list_namespaced_pod.call_args.kwargs['label_selector'] == \
            'serving.knative.dev/revision=rev-2'

    def test_image_pull_error_of_unschedulable_revision_raises(self):
        # Knative keeps reporting Unschedulable once the pod got a node and
        # cannot pull its image
        backend = _make_backend()
        backend.custom_api.get_namespaced_custom_object.return_value = _service(ready='False')
        pod = MagicMock()
        pod.status.container_statuses = [MagicMock()]
        pod.status.container_statuses[0].state.waiting.reason = 'ErrImagePull'
        pod.status.container_statuses[0].state.waiting.message = 'not found'
        backend.core_api.list_namespaced_pod.return_value.items = [pod]
        with pytest.raises(Exception, match='cannot pull its image: ErrImagePull'):
            backend._create_service('img', 512, 600)

    def test_unschedulable_revision_is_waited_for(self):
        backend = _make_backend()
        unschedulable = {'status': {'conditions': [{'type': 'Ready', 'status': 'False', 'reason': 'Unschedulable'}]}}
        backend.custom_api.get_namespaced_custom_object.side_effect = [
            _service(ready='False'), unschedulable,  # service, then its latest revision
            _service(),
        ]
        with patch.object(knative.time, 'sleep'):
            backend._create_service('img', 512, 600)
        assert backend.custom_api.get_namespaced_custom_object.call_args_list[1].kwargs['plural'] == 'revisions'


class TestIngressDetection:

    def _gateway(self, lb_ip=None, lb_hostname=None, node_port=31080):
        gateway = MagicMock()
        port = MagicMock(port=80, node_port=node_port)
        gateway.spec.ports = [MagicMock(port=443, node_port=31443), port]
        if lb_ip or lb_hostname:
            gateway.status.load_balancer.ingress = [MagicMock(ip=lb_ip, hostname=lb_hostname)]
        else:
            gateway.status.load_balancer.ingress = None
        return gateway

    def test_load_balancer_ip(self):
        backend = _make_backend()
        backend.core_api.read_namespaced_service.return_value = self._gateway(lb_ip='10.0.0.5')
        assert backend._detect_ingress_endpoint() == 'http://10.0.0.5:80'
        backend.core_api.read_namespaced_service.assert_called_with('kourier', 'kourier-system')

    def test_load_balancer_hostname(self):
        backend = _make_backend()
        backend.core_api.read_namespaced_service.return_value = self._gateway(lb_hostname='lb.aws.com')
        assert backend._detect_ingress_endpoint() == 'http://lb.aws.com:80'

    def test_node_port(self):
        backend = _make_backend()
        backend.core_api.read_namespaced_service.return_value = self._gateway()
        node = MagicMock()
        node.status.addresses = [MagicMock(type='InternalIP', address='172.18.0.2')]
        backend.core_api.list_node.return_value.items = [node]
        assert backend._detect_ingress_endpoint() == 'http://172.18.0.2:31080'

    def test_missing_gateway(self):
        backend = _make_backend()
        backend.core_api.read_namespaced_service.side_effect = ApiException(status=404)
        assert backend._detect_ingress_endpoint() is None


class TestInvoke:

    def test_through_ingress_with_host_header(self):
        backend = _make_backend({'ingress_endpoint': 'http://127.0.0.1:8080'})
        backend.custom_api.get_namespaced_custom_object.return_value = _service(
            url='https://svc.lithops.example.com'
        )
        with patch.object(knative.requests, 'post', return_value=_response(202, {'activationId': 'a1'})) as post:
            assert backend.invoke('img', 512, {'executor_id': 'e'}) == 'a1'
            assert backend.invoke('img', 512, {'executor_id': 'e'}) == 'a1'
        assert post.call_args.args[0] == 'http://127.0.0.1:8080/'
        assert post.call_args.kwargs['headers']['Host'] == 'svc.lithops.example.com'
        # The service URL is read once
        assert backend.custom_api.get_namespaced_custom_object.call_count == 1

    def test_direct_to_service_url(self):
        backend = _make_backend()
        backend.custom_api.get_namespaced_custom_object.return_value = _service()
        with patch.object(knative.requests, 'post', return_value=_response(200, {'preinstalls': []})) as post:
            meta = backend.invoke('img', 512, {'service_route': '/metadata'}, return_result=True)
        assert meta == {'preinstalls': []}
        assert post.call_args.args[0] == 'http://svc.lithops.example.com/metadata'
        assert 'Host' not in post.call_args.kwargs['headers']

    def test_incluster_uses_cluster_local_address(self):
        backend = _make_backend(incluster=True)
        with patch.object(knative.requests, 'post', return_value=_response(202, {'activationId': 'a1'})) as post:
            backend.invoke('img', 512, {})
        service_name = backend._format_service_name('img', 512)
        assert post.call_args.args[0] == f'http://{service_name}.lithops.svc/'
        backend.custom_api.get_namespaced_custom_object.assert_not_called()

    def test_cluster_local_url_from_outside_raises(self):
        backend = _make_backend()
        backend.custom_api.get_namespaced_custom_object.return_value = _service(
            url='http://svc.lithops.svc.cluster.local'
        )
        with pytest.raises(Exception, match='config-domain'):
            backend.invoke('img', 512, {})

    @pytest.mark.parametrize('status', knative.RETRY_STATUS_CODES)
    def test_overload_is_retried(self, status):
        backend = _make_backend(incluster=True)
        with patch.object(knative.requests, 'post', return_value=_response(status)):
            assert backend.invoke('img', 512, {}) is None

    @pytest.mark.parametrize('status', [404, 500, 502, 504])
    def test_other_errors_raise(self, status):
        backend = _make_backend(incluster=True)
        with patch.object(knative.requests, 'post', return_value=_response(status)):
            with pytest.raises(Exception, match=str(status) if status != 404 else 'not deployed'):
                backend.invoke('img', 512, {})


class TestListRuntimes:

    def _ksvc(self, name, memory, labels=None, image='docker.io/user/img:1'):
        return {
            'metadata': {'name': name},
            'spec': {'template': {
                'metadata': {'labels': labels if labels is not None
                             else {'type': 'lithops-runtime', 'lithops-version': '3-8-1'}},
                'spec': {'containers': [{'image': image, 'resources': {'requests': {'memory': memory}}}]},
            }},
        }

    def test_list(self):
        backend = _make_backend()
        backend.custom_api.list_namespaced_custom_object.return_value = {'items': [
            self._ksvc('a', '512Mi'),
            self._ksvc('b', '2Gi', image='docker.io/user/other:1'),
            self._ksvc('c', '512Mi', labels={'app': 'not-lithops'}),
            self._ksvc('d', '512Mi', labels={}),
        ]}
        assert backend.list_runtimes() == [
            ('docker.io/user/img:1', 512, '3.8.1', 'a'),
            ('docker.io/user/other:1', 2048, '3.8.1', 'b'),
        ]
        assert backend.list_runtimes('other') == [('docker.io/user/other:1', 2048, '3.8.1', 'b')]


class TestDeployRuntime:

    def test_a_metadata_failure_deletes_the_service(self):
        backend = _make_backend()
        backend._get_default_runtime_image_name = MagicMock(return_value='other')
        backend._create_container_registry_secret = MagicMock()
        backend._create_service = MagicMock()
        backend._generate_runtime_meta = MagicMock(side_effect=Exception('metadata down'))
        backend.delete_runtime = MagicMock()
        with pytest.raises(Exception, match='metadata down'):
            backend.deploy_runtime('img', 256, 60)
        backend.delete_runtime.assert_called_once_with('img', 256)

    def test_the_metadata_error_survives_a_failed_cleanup(self):
        backend = _make_backend()
        backend._get_default_runtime_image_name = MagicMock(return_value='other')
        backend._create_container_registry_secret = MagicMock()
        backend._create_service = MagicMock()
        backend._generate_runtime_meta = MagicMock(side_effect=Exception('metadata down'))
        backend.delete_runtime = MagicMock(side_effect=Exception('cleanup'))
        with pytest.raises(Exception, match='metadata down'):
            backend.deploy_runtime('img', 256, 60)

    def test_unknown_kube_context_names_the_known_ones(self, tmp_path):
        kubeconfig = tmp_path / 'kubeconfig'
        kubeconfig.write_text('apiVersion: v1\n')
        contexts = (
            [{'name': 'kind', 'context': {'namespace': 'ns', 'cluster': 'c'}}],
            {'name': 'kind', 'context': {'namespace': 'ns', 'cluster': 'c'}},
        )
        with patch.object(knative, 'load_kube_config'), \
                patch.object(knative, 'list_kube_config_contexts', return_value=contexts), \
                patch.object(knative, 'client'):
            with pytest.raises(Exception, match="context 'typo' was not found"):
                KnativeServingBackend(
                    {'kubecfg_path': str(kubeconfig), 'kubecfg_context': 'typo'},
                    MagicMock(),
                )


class TestDeleteRuntime:

    def test_waits_until_gone(self):
        backend = _make_backend()
        backend.custom_api.get_namespaced_custom_object.side_effect = [_service(), ApiException(status=404)]
        with patch.object(knative.time, 'sleep'):
            backend.delete_runtime('img', 512)
        body = backend.custom_api.delete_namespaced_custom_object.call_args.kwargs['body']
        assert body.propagation_policy == 'Foreground'

    def test_missing_service_ignored(self):
        backend = _make_backend()
        backend.custom_api.delete_namespaced_custom_object.side_effect = ApiException(status=404)
        backend.delete_runtime('img', 512)
        backend.custom_api.get_namespaced_custom_object.assert_not_called()
