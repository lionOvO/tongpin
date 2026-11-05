"""Bounded provider adapters; tool execution remains in the application."""
import json
import time
import asyncio
from contextlib import contextmanager
import httpx

MAX_RESPONSE_BYTES = 2_000_000
MAX_ERROR_BYTES = 16_384


class ModelClient:
    """Sync gateway facade with a cancellable wall-clock HTTP deadline.

    A read timeout alone is reset by provider keep-alives. Structured reports
    remain buffered; Agent reply previews use the separate incremental adapter.
    """
    def __init__(self, timeout=90):
        self.timeout = timeout

    def __enter__(self): return self
    def __exit__(self, *args): pass

    async def _request(self, url, headers, json):
        async def receive():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream('POST', url, headers=headers, json=json) as response:
                    limit = MAX_RESPONSE_BYTES if response.is_success else MAX_ERROR_BYTES
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > limit:
                            if response.is_success: raise ValueError('model response too large')
                            body.clear()  # Error bodies are unnecessary beyond the safe diagnostic cap.
                            break
                    response_headers = {key: value for key, value in response.headers.items()
                        if key.lower() not in {'content-encoding', 'content-length', 'transfer-encoding'}}
                    return httpx.Response(response.status_code, headers=response_headers,
                        content=bytes(body), request=response.request)
        try:
            return await asyncio.wait_for(receive(), timeout=self.timeout)
        except TimeoutError:
            raise httpx.ReadTimeout('model request exceeded total time limit') from None

    def post(self, url, headers, json):
        return asyncio.run(self._request(url, headers, json))

    def tool_stream(self, url, headers, payload, on_delta):
        """Read real provider SSE incrementally under a total HTTP deadline."""
        async def receive():
            text = ''; calls = {}; finish = None; counts = {}; size = 0; done = False
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream('POST', url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        size += len(line.encode('utf-8'))
                        if size > MAX_RESPONSE_BYTES: raise ValueError('stream too large')
                        if not line.startswith('data:'): continue
                        raw = line[5:].strip()
                        if not raw: continue
                        if raw == '[DONE]': done = True; break
                        event = json.loads(raw)
                        if event.get('error'): raise ValueError('provider stream failed')
                        if event.get('usage'): counts = event['usage']
                        choices = event.get('choices') or []
                        if not choices: continue
                        choice = choices[0]; delta = choice.get('delta') or {}
                        if delta.get('refusal'): raise ValueError('refusal')
                        if choice.get('finish_reason'): finish = choice['finish_reason']
                        if delta.get('content'):
                            text += delta['content']; on_delta(delta['content'])
                        for fragment in delta.get('tool_calls') or []:
                            index = fragment['index']
                            if not isinstance(index, int) or not 0 <= index < 4: raise ValueError('invalid tool index')
                            call = calls.setdefault(index, {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
                            if fragment.get('id'): call['id'] += fragment['id']
                            if fragment.get('type') and fragment['type'] != 'function': raise ValueError('invalid tool type')
                            for key in ('name', 'arguments'):
                                call['function'][key] += (fragment.get('function') or {}).get(key) or ''
                            if len(call['function']['arguments']) > 4000: raise ValueError('tool args too large')
            if not done or finish not in {'stop', 'tool_calls'}: raise ValueError('incomplete stream')
            return {'choices': [{'finish_reason': finish, 'message': {'role': 'assistant',
                'content': text or None, 'tool_calls': [calls[i] for i in sorted(calls)]}}], 'usage': counts}
        try:
            return asyncio.run(asyncio.wait_for(receive(), timeout=self.timeout))
        except TimeoutError:
            raise httpx.ReadTimeout('model stream exceeded total deadline') from None

    @contextmanager
    def stream(self, method, url, headers, json):
        assert method == 'POST'
        yield self.post(url, headers, json)


def raise_provider_status(response, *, streaming=False):
    """Keep only recognized error codes; provider text may contain private input."""
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        # Do not consume a successful stream or persist the raw error body.
        try:
            if streaming:
                chunks = bytearray()
                for chunk in response.iter_bytes(chunk_size=4096):
                    chunks.extend(chunk)
                    if len(chunks) > MAX_ERROR_BYTES:
                        break
                body = bytes(chunks)
            else:
                body = response.content
            if len(body) <= MAX_ERROR_BYTES:
                obj = json.loads(body)
                detail = obj.get('error') if isinstance(obj, dict) else None
                if isinstance(detail, dict) and detail.get('code') == 'stream_required':
                    error.provider_code = 'stream_required'
        except (httpx.HTTPError, ValueError, TypeError):
            pass
        raise


def request_json(client, profile, system, value, max_tokens, timeout=90):
    messages = [{'role':'system','content':system},{'role':'user','content':json.dumps(value,ensure_ascii=False)}]
    headers = {'Authorization':f'Bearer {profile.api_key}'}
    if profile.protocol == 'responses':
        # Some compatible gateways check input (not instructions) for JSON mode.
        input_text = ('请按 instructions 输出 JSON 对象。\n' if profile.json_mode else '') + messages[1]['content']
        payload = {'model':profile.model,'instructions':system,
            'input':[{'role':'user','content':[{'type':'input_text','text':input_text}]}],
            'store':False,'stream':profile.stream,'max_output_tokens':max_tokens or 4500}
        if profile.json_mode: payload['text'] = {'format':{'type':'json_object'}}
        url = profile.base_url + '/responses'
        if profile.stream:
            obj = stream_response(client,url,headers,payload,timeout=timeout)
        else:
            response=client.post(url,headers=headers,json=payload); raise_provider_status(response)
            if len(response.content) > MAX_RESPONSE_BYTES: raise ValueError('model response too large')
            obj=response.json()
        return parse_responses(obj)
    payload={'model':profile.model,'messages':messages,'temperature':0,'max_tokens':max_tokens or 4500}
    if profile.json_mode: payload['response_format']={'type':'json_object'}
    if profile.deepseek_thinking: payload['thinking']={'type':'disabled'}
    response=client.post(profile.base_url+'/chat/completions',headers=headers,json=payload); raise_provider_status(response)
    if len(response.content) > MAX_RESPONSE_BYTES: raise ValueError('model response too large')
    obj=response.json(); choice=obj['choices'][0]
    if choice.get('finish_reason') not in {None,'stop'} or choice['message'].get('refusal') or choice['message'].get('tool_calls'):
        raise ValueError('model did not return a complete text answer')
    return choice['message']['content'], usage(obj.get('usage') or {},'prompt_tokens','completion_tokens')


def usage(value,input_key,output_key):
    # Persist aggregate counts only, never provider response text or IDs.
    return {'prompt_tokens':max(0,int(value.get(input_key,0))), 'completion_tokens':max(0,int(value.get(output_key,0)))}


def request_tool_turn(client, profile, messages, tools, max_tokens=4500, on_delta=None):
    """Separate from strict JSON/report transport: accept only text or function calls."""
    if profile.id not in {'deepseek', 'deepseek-pro'} or profile.protocol != 'chat_completions':
        raise ValueError('tool collaboration requires a supported DeepSeek profile')
    payload = {'model': profile.model, 'messages': messages, 'tools': tools,
               'tool_choice': 'auto', 'temperature': 0, 'max_tokens': max_tokens}
    if profile.deepseek_thinking: payload['thinking'] = {'type': 'disabled'}
    url = profile.base_url + '/chat/completions'; headers = {'Authorization': f'Bearer {profile.api_key}'}
    if on_delta is not None:
        payload.update(stream=True, stream_options={'include_usage': True})
        obj = client.tool_stream(url, headers, payload, on_delta)
    else:
        response = client.post(url, headers=headers, json=payload)
        raise_provider_status(response)
        if len(response.content) > MAX_RESPONSE_BYTES: raise ValueError('model response too large')
        obj = response.json()
    choice = obj['choices'][0]; message = choice['message']
    calls = message.get('tool_calls') or []
    if message.get('refusal') or len(calls) > 4:
        raise ValueError('invalid tool response')
    if calls:
        if choice.get('finish_reason') != 'tool_calls': raise ValueError('incomplete tool calls')
        clean, ids = [], set()
        for call in calls:
            fn = call.get('function', {}); ident = call.get('id')
            if (call.get('type') != 'function' or not isinstance(ident, str) or not 1 <= len(ident) <= 100
                    or ident in ids or not isinstance(fn.get('name'), str)
                    or not isinstance(fn.get('arguments'), str) or len(fn['arguments']) > 4000):
                raise ValueError('invalid tool call')
            ids.add(ident)
            clean.append({'id': ident, 'type': 'function', 'function': {'name': fn['name'], 'arguments': fn['arguments']}})
        result = {'role': 'assistant', 'content': None, 'tool_calls': clean}
    else:
        if choice.get('finish_reason') != 'stop' or not isinstance(message.get('content'), str):
            raise ValueError('incomplete answer')
        result = {'role': 'assistant', 'content': message['content']}
    return result, usage(obj.get('usage') or {}, 'prompt_tokens', 'completion_tokens')


def parse_responses(obj):
    if not isinstance(obj,dict) or not isinstance(obj.get('output'),list):
        raise ValueError('invalid response envelope')
    if obj.get('status') != 'completed' or obj.get('error') or obj.get('incomplete_details'):
        raise ValueError('response incomplete')
    texts=[]
    for item in obj.get('output',[]):
        if not isinstance(item,dict): raise ValueError('invalid response item')
        if item.get('type') == 'reasoning': continue
        if item.get('type') != 'message' or item.get('role') != 'assistant':
            raise ValueError('unexpected model tool or output item')
        if item.get('status','completed') != 'completed': raise ValueError('message incomplete')
        if not isinstance(item.get('content'),list): raise ValueError('invalid response content')
        for part in item.get('content',[]):
            if not isinstance(part,dict): raise ValueError('invalid response content part')
            if part.get('type') != 'output_text': raise ValueError('refusal or unsupported output')
            texts.append(part['text'])
    if not texts: raise ValueError('response has no text')
    return ''.join(texts), usage(obj.get('usage') or {},'input_tokens','output_tokens')


def stream_response(client,url,headers,payload,timeout=90):
    completed=None; size=0; data=[]
    deadline=time.monotonic()+timeout
    def event(lines):
        nonlocal completed
        raw='\n'.join(lines)
        if not raw or raw == '[DONE]': return
        obj=json.loads(raw)
        if obj.get('type') in {'error','response.failed','response.incomplete'}:
            raise ValueError('stream failed or incomplete')
        if obj.get('type') == 'response.completed': completed=obj['response']
    with client.stream('POST',url,headers=headers,json=payload) as response:
        raise_provider_status(response, streaming=True)
        for line in response.iter_lines():
            if time.monotonic() > deadline: raise httpx.ReadTimeout('model stream exceeded time limit')
            size+=len(line.encode('utf-8'))
            if size > MAX_RESPONSE_BYTES: raise ValueError('model stream too large')
            if line.startswith('data:'): data.append(line[5:].lstrip())
            elif not line:
                event(data); data=[]
        event(data)
    if completed is None: raise ValueError('stream ended before completion')
    return completed
