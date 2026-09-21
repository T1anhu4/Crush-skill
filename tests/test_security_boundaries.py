import asyncio
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from crush_core.provider import ProviderError, completion
from crush_core.server import MAX_REQUEST_BYTES, RequestBodyLimit, create_app


@contextmanager
def model_server(redirect=False):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            if redirect:
                self.send_response(302)
                self.send_header('Location', f'http://localhost:{self.server.server_port}/sink')
                self.end_headers()
            else:
                self.do_GET()

        def do_GET(self):
            received.append(self.headers.get('Authorization'))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({'choices': [{'message': {'content': '{"action":"wait"}'}}]}).encode())

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', received
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_provider_does_not_forward_credentials_on_redirect():
    with model_server(redirect=True) as (base, received):
        error = None
        try:
            completion(base, 'synthetic-test-key', {})
        except ProviderError as exc:
            error = exc
        assert received == [], 'Redirect destination must never receive a request'
        assert error is not None
        assert error.code == 'redirect'
        assert 'synthetic-test-key' not in str(error)


def test_direct_local_model_still_works():
    with model_server() as (base, received):
        assert completion(base, 'synthetic-test-key', {}) == {'action': 'wait'}
        assert received == ['Bearer synthetic-test-key']


@pytest.mark.parametrize('mode', ['openai', 'anthropic', 'gemini'])
def test_legacy_cli_does_not_follow_model_redirects(monkeypatch, mode):
    from crush_cli.app import ChatClient, ModelError
    for name in ('CRUSH_CHAT_API_KEY', 'CRUSH_CHAT_API_BASE', 'CRUSH_CHAT_PROVIDER_MODE',
                 'CRUSH_CHAT_MODEL', 'OPENAI_API_BASE', 'OPENAI_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    with model_server(redirect=True) as (base, received):
        client = ChatClient({'api_base': base, 'api_key': 'synthetic-test-key',
                             'model': 'test', 'provider_mode': mode})
        try:
            client.reply('synthetic role', 'synthetic hello')
        except ModelError:
            pass
        assert received == [], 'Legacy CLI must not follow provider redirects'


def test_skill_analyzer_does_not_follow_model_redirects(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'Crush.skill'))
    from engines.dialogue_analyzer import analyze_llm
    with model_server(redirect=True) as (base, received):
        analyze_llm('你好', api_base=base, api_key='synthetic-test-key')
        assert received == [], 'Skill analysis must not follow provider redirects'


def test_cli_http_error_does_not_echo_provider_payload():
    from crush_cli.app import _format_http_error
    message = _format_http_error(401, 'https://example.invalid/v1', 'test',
        '{"error":{"message":"synthetic-private-key and private conversation"}}')
    assert 'synthetic-private' not in message
    assert 'private conversation' not in message
    assert '401' in message
    assert '/setup' in message


@pytest.mark.parametrize('declared', [None, '2'])
def test_actual_body_limit_prevents_session_creation(tmp_path, declared):
    with TestClient(create_app(tmp_path, run_worker=False)) as client:
        headers = {'x-crush-token': client.get('/api/bootstrap').json()['token'],
                   'Content-Type': 'application/json'}
        if declared is not None:
            headers['Content-Length'] = declared
        body = json.dumps({'ignored': 'x' * 70000}).encode()
        response = client.post('/api/sessions', content=iter([body[:10000], body[10000:]]), headers=headers)
        assert response.status_code == 413
        assert client.get('/api/sessions').json() == []


def test_validation_error_never_echoes_api_key(tmp_path):
    with TestClient(create_app(tmp_path, run_worker=False)) as client:
        token = client.get('/api/bootstrap').json()['token']
        response = client.post('/api/settings', json={'base': 'https://example.invalid',
            'model': 'test', 'key': 'synthetic-private-' * 130}, headers={'x-crush-token': token})
        assert response.status_code == 422
        assert 'synthetic-private' not in response.text
        assert 'error' in response.json()


def test_malformed_host_is_rejected_without_server_error(tmp_path):
    with TestClient(create_app(tmp_path, run_worker=False), raise_server_exceptions=False) as client:
        assert client.get('/api/bootstrap', headers={'host': '[broken'}).status_code == 403


def test_full_length_chinese_message_accepts_escaped_json(tmp_path):
    with TestClient(create_app(tmp_path, run_worker=False)) as client:
        headers = {'x-crush-token': client.get('/api/bootstrap').json()['token'],
                   'Content-Type': 'application/json'}
        sid = client.post('/api/sessions', json={}, headers=headers).json()['id']
        response = client.post(f'/api/sessions/{sid}/messages', headers=headers,
            content=json.dumps({'content': '你好' * 2000, 'request_id': 'escaped-chinese-message'}))
        assert response.status_code == 200
        assert response.json()['messages'][-1]['content'] == '你好' * 2000


def test_trailing_slash_does_not_discard_saved_key(tmp_path):
    from crush_core.server import Settings
    settings = Settings(tmp_path / 'provider.json')
    settings.save({'base': 'https://example.invalid/v1/', 'model': 'test', 'key': 'synthetic-test-key'})
    settings.save({'base': 'https://example.invalid/v1', 'model': 'test-new', 'key': ''})
    assert settings.get()['key'] == 'synthetic-test-key'
    assert settings.public()['model'] == 'test-new'
    with pytest.raises(ValueError):
        settings.save({'base': 'https://different.invalid/v1', 'model': 'test', 'key': ''})


def test_stream_limit_stops_reading_before_route_or_remaining_chunks():
    async def scenario():
        called = []
        output = []
        chunks = iter([
            {'type': 'http.request', 'body': b'x' * MAX_REQUEST_BYTES, 'more_body': True},
            {'type': 'http.request', 'body': b'x', 'more_body': True},
        ])

        async def receive():
            return next(chunks)  # A third read would fail this test.

        async def send(message):
            output.append(message)

        async def route(*args):
            called.append(True)

        await RequestBodyLimit(route)({'type': 'http', 'method': 'POST',
                                      'path': '/api/sessions'}, receive, send)
        assert not called
        assert output[0]['status'] == 413

    asyncio.run(scenario())


def test_stream_limit_replays_valid_chunked_body_once():
    async def scenario():
        chunks = iter([
            {'type': 'http.request', 'body': b'{', 'more_body': True},
            {'type': 'http.request', 'body': b'}', 'more_body': False},
            {'type': 'http.disconnect'},
        ])

        async def receive():
            return next(chunks)

        async def route(scope, replay, send):
            assert await replay() == {'type': 'http.request', 'body': b'{}', 'more_body': False}
            assert await replay() == {'type': 'http.disconnect'}

        await RequestBodyLimit(route)({'type': 'http', 'method': 'POST',
                                      'path': '/api/sessions'}, receive, None)

    asyncio.run(scenario())
