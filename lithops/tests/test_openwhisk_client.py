#
# The OpenWhisk client against a fake controller. No server is contacted.
#

import json

import pytest
import requests

from lithops.libs.openwhisk.client import OpenWhiskClient


def _response(status, body=None):
    response = requests.Response()
    response.status_code = status
    response.url = 'http://localhost:3233/api/v1/x'
    response._content = b'' if body is None else json.dumps(body).encode()
    return response


def _client(responses=None, errors=None):
    """A client whose session replays the given responses, then the errors"""
    client = OpenWhiskClient('http://localhost:3233', 'guest', api_key='uuid:secret')
    calls = []
    pending = list(responses or [])
    failures = list(errors or [])

    def request(method, url, params=None, json=None, timeout=None):
        calls.append({'method': method, 'url': url, 'params': params, 'json': json, 'timeout': timeout})
        if failures:
            raise failures.pop(0)
        return pending.pop(0)

    client.session.request = request
    return client, calls


def test_http_endpoint_is_kept_and_key_is_basic_auth():
    client, _ = _client()
    assert client.endpoint == 'http://localhost:3233'
    assert client.session.headers['Authorization'].startswith('Basic ')

    bare = OpenWhiskClient('ow.example.com', 'guest', auth='Bearer token')
    assert bare.endpoint == 'https://ow.example.com'
    assert bare.session.headers['Authorization'] == 'Bearer token'


def test_create_action_sends_docker_exec():
    client, calls = _client([_response(200, {})])
    client.create_action('pkg', 'hello', image_name='openwhisk/python3action', code=b'zip', memory=256, timeout=60000)

    call = calls[0]
    assert call['method'] == 'PUT'
    assert call['url'] == 'http://localhost:3233/api/v1/namespaces/guest/actions/pkg/hello'
    assert call['params'] == {'overwrite': 'true'}
    assert call['json']['limits'] == {'memory': 256, 'timeout': 60000}
    assert call['json']['exec']['kind'] == 'blackbox'
    assert call['json']['exec']['image'] == 'openwhisk/python3action'
    assert call['json']['exec']['binary'] is True
    assert call['json']['exec']['code']  # base64 of the zip


def test_source_action_has_no_image():
    client, calls = _client([_response(200, {})])
    client.create_action('pkg', 'hello', code='def main(args):\n    return {}\n', kind='python:3', is_binary=False)
    exec_ = calls[0]['json']['exec']
    assert exec_ == {'kind': 'python:3', 'binary': False, 'code': 'def main(args):\n    return {}\n'}


def test_docker_action_without_image_is_rejected():
    client, calls = _client()
    with pytest.raises(ValueError, match='image'):
        client.create_action('pkg', 'hello', kind='blackbox')
    assert calls == []


def test_lists_follow_pages_and_a_missing_collection_is_empty():
    page = [{'name': str(i)} for i in range(200)]
    client, calls = _client([_response(200, page), _response(200, [{'name': 'last'}]), _response(404)])

    assert len(client.list_actions('pkg')) == 201
    assert [call['params']['skip'] for call in calls[:2]] == [0, 200]
    assert calls[0]['url'].endswith('/actions/pkg/')
    assert client.list_packages() == []


def test_delete_of_missing_action_and_existing_package():
    client, calls = _client([_response(404), _response(409)])
    client.delete_action('pkg', 'gone')
    client.create_package('pkg')
    assert calls[1]['params'] == {'overwrite': 'false'}


def _scripted_invoke(client, outcomes):
    """Makes invoke() replay (status, body) pairs, or raise the given errors"""
    calls = []
    pending = list(outcomes)

    def post(url, payload):
        calls.append({'url': url, 'payload': payload})
        outcome = pending.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        status, body = outcome
        raw = b'' if body is None else json.dumps(body).encode()
        return status, raw

    client._post_invoke = post
    return calls


def test_invoke_returns_activation_id_status_or_none():
    client, _ = _client()
    calls = _scripted_invoke(client, [
        (202, {'activationId': 'act-1'}),
        (401, None),
        (404, None),
        (429, None),
        (400, {'error': 'The requested action does not exist'}),
    ])
    assert client.invoke('pkg', 'hello', {'n': 1}) == 'act-1'
    assert calls[0]['payload'] == {'n': 1}
    assert calls[0]['url'].startswith('http://localhost:3233/')
    assert client.invoke('pkg', 'hello') == 401
    assert client.invoke('pkg', 'hello') == 404
    assert client.invoke('pkg', 'hello') is None
    with pytest.raises(Exception, match='does not exist'):
        client.invoke('pkg', 'hello')


def test_invoke_retries_a_dropped_connection_once():
    client, _ = _client()
    calls = _scripted_invoke(client, [OSError('reset'), (202, {'activationId': 'act-1'})])
    assert client.invoke('pkg', 'hello') == 'act-1'
    assert len(calls) == 2

    client, _ = _client()
    calls = _scripted_invoke(client, [OSError('reset'), OSError('reset')])
    with pytest.raises(OSError):
        client.invoke('pkg', 'hello')
    assert len(calls) == 2


def test_invoke_opens_a_fresh_connection_and_closes_it(monkeypatch):
    opened = []

    class _Response:
        status = 202

        @staticmethod
        def read():
            return b'{"activationId": "act-1"}'

    class _Conn:
        def __init__(self, host, port=None, timeout=None, context=None):
            opened.append(self)
            self.host, self.port, self.timeout, self.context = host, port, timeout, context
            self.closed = False

        def request(self, method, path, body=None, headers=None):
            self.sent = (method, path, body, headers)

        def getresponse(self):
            return _Response()

        def close(self):
            self.closed = True

    monkeypatch.setattr('lithops.libs.openwhisk.client.http.client.HTTPConnection', _Conn)
    client, _ = _client()
    assert client.invoke('pkg', 'hello', {'n': 1}) == 'act-1'
    conn = opened[0]
    assert conn.closed
    assert conn.host == 'localhost' and conn.port == 3233
    method, path, body, headers = conn.sent
    assert method == 'POST'
    assert path == '/api/v1/namespaces/guest/actions/pkg/hello'
    assert headers['Connection'] == 'close'
    assert json.loads(body) == {'n': 1}

    monkeypatch.setattr('lithops.libs.openwhisk.client.http.client.HTTPSConnection', _Conn)
    secure = OpenWhiskClient('https://ow.example.com', 'guest', api_key='uuid:secret', insecure=True)
    assert secure.invoke('pkg', 'hello') == 'act-1'
    assert opened[1].context is not None


def test_invoke_with_result_polls_until_the_activation_finishes(monkeypatch):
    monkeypatch.setattr('lithops.libs.openwhisk.client.time.sleep', lambda seconds: None)
    client, _ = _client([
        _response(202, {'activationId': 'act-1'}),
        _response(404),
        _response(200, {'activationId': 'act-1', 'response': {'status': 'success', 'result': {'ok': True}}}),
    ])
    assert client.invoke_with_result('pkg', 'hello', {'get_metadata': True}) == {'ok': True}


def test_invoke_with_result_reports_a_failed_activation(monkeypatch):
    monkeypatch.setattr('lithops.libs.openwhisk.client.time.sleep', lambda seconds: None)
    client, _ = _client([
        _response(200, {'activationId': 'act-1'}),
        _response(200, {'response': {'status': 'application error', 'result': {'error': 'boom'}}}),
    ])
    with pytest.raises(Exception, match='boom'):
        client.invoke_with_result('pkg', 'hello', timeout=5)
