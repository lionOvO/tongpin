import time
import asyncio
import httpx
import pytest
from app.model_transport import ModelClient, request_json
from app.model_catalog import ModelProfile


def test_keepalive_bytes_cannot_extend_total_model_request_deadline(monkeypatch):
    closed = []
    class KeepAlive(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(.005)
                yield b' '
        async def aclose(self): closed.append(True)
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=KeepAlive()))
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=transport, **kw))
    start = time.monotonic()
    with pytest.raises(httpx.TimeoutException):
        ModelClient(timeout=.04).post('https://example.invalid', headers={}, json={})
    assert time.monotonic() - start < .3 and closed


@pytest.mark.parametrize('protocol,stream', [('chat_completions', False), ('responses', False), ('responses', True)])
def test_deadline_transport_keeps_both_protocols_and_sse_parsing(protocol, stream, monkeypatch):
    body = {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
        'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]}
    import json
    def handle(request):
        if protocol == 'chat_completions':
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]})
        if stream:
            return httpx.Response(200, content=('data: ' + json.dumps({'type': 'response.completed', 'response': body}) + '\n\n').encode())
        return httpx.Response(200, json=body)
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=transport, **kw))
    profile = ModelProfile('test', 'Synthetic', 'test', 'test', protocol, 'https://example.invalid', 'test-key', stream=stream)
    with ModelClient(timeout=1) as client:
        output, _ = request_json(client, profile, 'JSON', {'synthetic': True}, 100, timeout=1)
    assert output == '{"ok":true}'


def test_gzip_provider_body_is_decoded_once(monkeypatch):
    import gzip
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200,
        headers={'Content-Encoding': 'gzip'}, content=gzip.compress(b'{"ok":true}')))
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=transport, **kw))
    assert ModelClient(timeout=1).post('https://example.invalid', headers={}, json={}).json() == {'ok': True}
