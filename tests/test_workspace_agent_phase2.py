"""Real graph/services/SSE, synthetic materials and local scripted model only."""
import json
import time
import threading
import asyncio
import httpx
import pytest
from test_ai_workspace import setup, PATH, TEXT
from test_material_agent import calls, answer, script, send
from app.deterministic import parse_jd
from app.workspace_stream import ReplyPreview
from app.model_transport import ModelClient, request_tool_turn


def job(app, actor, title='Python 后端', **changes):
    text = '岗位要求：本科，使用 Python 编写业务接口及测试，参与业务项目。'
    return app.state.service.db.insert('job_profiles', dict(title=title, source_jd=text, profile=parse_jd(text),
        status='已确认', version=1, published=False, **changes), actor)


def simple_result(tier='B4'):
    return {'dimensions': [{'dimension_id': 'D3', 'name': '项目经验', 'tier': tier, 'evidence': ['合成项目']}],
        'skill_levels': [], 'sort_key': {}, 'assessed_at': '2026-10-27T00:00:00Z'}


def test_query_dispatch_progress_results_and_scope(setup, monkeypatch):
    app, first, second, user, other, _, row = setup
    visible = [job(app, user['actor'], 'Python 接口'), job(app, user['actor'], 'Python 平台')]
    job(app, other['actor'], '不应出现的私有岗位')
    gate = threading.Event(); entered = threading.Event(); evaluations = []
    def evaluate(target, resume, actor):
        evaluations.append((target['id'], resume['id'], actor)); entered.set(); assert gate.wait(8)
        return simple_result('B4' if target['id'] == visible[0]['id'] else 'B3')
    monkeypatch.setattr(app.state.service, 'evaluate', evaluate)
    def start(messages):
        result = json.loads(messages[-1]['content'])
        assert len(result['jobs']) == 2 and '不应出现' not in str(result)
        assert 'job_id' not in str(result) and 'owner' not in str(result)
        return calls(('start_comparison', {'job_refs': [j['ref'] for j in result['jobs']]}))
    script(app, monkeypatch, [calls(('read_resume', {}), ('search_jobs', {'query': 'Python'})), start, answer()])
    try:
        response = send(first, row, message='根据我的简历找 Python 岗位并分析契合度。')
        assert response.status_code == 200, response.text
        body = response.json(); task = body['job_assistance']['comparison']
        assert entered.wait(3) and task['total'] == 2 and task['status'] in {'queued', 'running'}
        assert len(evaluations) == 1 and 'targets' not in task and 'resume_snapshot' not in task
        assert second.get(f"{PATH}/{row['id']}").status_code == 404
        assert second.get('/compare/tasks/' + task['id']).status_code == 404
    finally: gate.set()
    for _ in range(150):
        body = first.get(f"{PATH}/{row['id']}").json(); task = body['job_assistance']['comparison']
        if task['status'] not in {'queued', 'running'}: break
        time.sleep(.02)
    assert task['status'] == 'completed' and len(evaluations) == 2
    assert [r['fit_summary']['band'] for r in task['ranked_results']] == ['high', 'medium']
    assert [r['rank'] for r in task['ranked_results']] == [1, 2]
    script(app, monkeypatch, [calls(('read_comparison', {})), {'role': 'assistant', 'content': json.dumps({'reply': '已读取分析结果，具体档位与依据见岗位卡片。', 'findings': [], 'questions': [], 'rewrites': []})}])
    assert send(first, body).status_code == 200 and len(evaluations) == 2
    app.state.service.db.update('job_profiles', visible[0]['id'], {'version': 2})
    fresh = first.get(f"{PATH}/{row['id']}").json()['job_assistance']
    assert len(fresh['jobs']) == 1 and fresh['comparison']['unavailable_count'] == 1
    assert fresh['comparison']['ranked_results'][0]['rank'] == 1


@pytest.mark.parametrize('args', [{'job_refs': ['forged-ref']}, {'job_refs': ['x'], 'resume_id': 'foreign'}])
def test_comparison_tool_rejects_arbitrary_ids(setup, monkeypatch, args):
    app, first, _, _, _, _, row = setup
    script(app, monkeypatch, [calls(('start_comparison', args))])
    assert send(first, row).status_code in {409, 422}
    assert not app.state.service.db.list('job_comparison_runs')


def test_same_turn_repeated_dispatch_is_idempotent(setup, monkeypatch):
    app, first, _, user, _, _, row = setup
    job(app, user['actor']); count = []
    monkeypatch.setattr(app.state.service, 'evaluate', lambda *a: (count.append(1), simple_result())[1])
    def dispatch(messages):
        refs = [j['ref'] for j in json.loads(messages[-1]['content'])['jobs']]
        response = calls(('start_comparison', {'job_refs': refs}))
        return response
    def repeat(messages):
        previous = next(m for m in messages if m.get('tool_calls') and m['tool_calls'][0]['function']['name'] == 'start_comparison')
        value = json.loads(json.dumps(previous)); value['tool_calls'][0]['id'] = 'different-call'
        return value
    script(app, monkeypatch, [calls(('read_resume', {}), ('search_jobs', {})), dispatch, repeat, answer()])
    result = send(first, row)
    assert result.status_code == 200, result.text
    assert len(app.state.service.db.list('job_comparison_runs')) == 1


def test_revocation_between_search_and_dispatch_prevents_task(setup, monkeypatch):
    app, first, _, user, _, _, row = setup
    selected = job(app, user['actor'])
    def revoke(messages):
        ref = json.loads(messages[-1]['content'])['jobs'][0]['ref']
        with app.state.service.db.transaction() as cx:
            cx.execute('UPDATE job_profiles SET owner=? WHERE id=?', ('candidate:elsewhere', selected['id']))
        return calls(('start_comparison', {'job_refs': [ref]}))
    script(app, monkeypatch, [calls(('search_jobs', {})), revoke])
    result = send(first, row)
    assert result.status_code == 409 and not app.state.service.db.list('job_comparison_runs')


def test_sse_incremental_reply_only_before_final_validation(setup, monkeypatch):
    app, first, second, user, _, _, row = setup
    sequence = iter([calls(('read_resume', {})), answer(rewrites=False)])
    def provider(messages, tools, **kwargs):
        result = next(sequence)
        if result.get('content'):
            for chunk in [result['content'][:20], result['content'][20:32], result['content'][32:]]:
                kwargs['on_delta'](chunk)
        return result
    monkeypatch.setattr(app.state.service.gateway, 'tool_step', provider)
    body = {'agent': True, 'action': 'chat', 'message': '分析简历', 'expected_version': row['version']}
    assert second.post(f"{PATH}/{row['id']}/turns/stream", json=body).status_code == 404
    response = first.post(f"{PATH}/{row['id']}/turns/stream", json=body)
    assert response.status_code == 200 and response.headers['x-accel-buffering'] == 'no'
    events = [block for block in response.text.split('\n\n') if block.startswith('event:')]
    previews = [json.loads(block.split('data: ')[1]) for block in events if block.startswith('event: preview')]
    assert len(previews) >= 2 and len(previews[0]) < len(previews[-1])
    assert all('source_id' not in value and 'citations' not in value for value in previews)
    final = json.loads(events[-1].split('data: ')[1])
    assert events[-1].startswith('event: done') and final['messages'][-1]['text'] == previews[-1]
    assert final['agent_run']['preview'] == '' and final['agent_run']['status'] == 'completed'


def test_invalid_stream_preview_never_saved(setup, monkeypatch):
    app, first, _, _, _, _, row = setup
    def invalid(messages, tools, **kwargs):
        result = answer(quote='原文不存在')
        kwargs['on_delta'](result['content'])
        return result
    monkeypatch.setattr(app.state.service.gateway, 'tool_step', invalid)
    response = first.post(f"{PATH}/{row['id']}/turns/stream", json={'agent': True, 'message': '分析', 'expected_version': row['version']})
    assert 'event: preview' in response.text and 'event: error' in response.text and 'event: done' not in response.text
    saved = first.get(f"{PATH}/{row['id']}").json()
    assert not saved['messages'] and saved['agent_run']['preview'] == ''


def test_selected_rewrites_only_and_confirmation_switches_version(setup, monkeypatch):
    app, first, _, _, _, resume, row = setup
    output = answer(rewrites=True); obj = json.loads(output['content'])
    second_before = TEXT.splitlines()[1]
    obj['rewrites'].append({'source_id': 'R2', 'before': second_before, 'after': '技能：SQL、Python', 'reason': '调整顺序', 'citations': [{'source_id': 'R2', 'quote': second_before}]})
    output['content'] = json.dumps(obj)
    script(app, monkeypatch, [calls(('read_resume', {})), calls(('prepare_draft', {'source_ids': ['R2', 'R3']})), output])
    row = send(first, row).json(); draft = row['drafts'][-1]
    response = first.post(f"{PATH}/{row['id']}/drafts/confirm", json={'draft_id': draft['id'], 'expected_version': row['version'],
        'indices': [0], 'continue_in_workspace': True})
    assert response.status_code == 200, response.text
    body = response.json(); saved = app.state.service.db.get('resumes', body['resume']['id'])
    assert second_before in saved['text'] and '技能：SQL、Python' not in saved['text']
    assert saved['revision_basis'] == [obj['rewrites'][0]] and saved['parent_resume_id'] == resume['id']
    assert app.state.service.db.get('resumes', resume['id'])['text'] == TEXT
    assert body['session']['resume_id'] == saved['id'] and body['session']['material_epoch'] == 1
    fresh = first.get(f"{PATH}/{row['id']}").json()
    assert fresh['resume_id'] == saved['id'] and fresh['resume']['text'] == saved['text']
    assert app.state.service.db.list('ai_sessions', resume_id=saved['id'])[0]['id'] == row['id']
    assert first.post(f"{PATH}/{row['id']}/drafts/confirm", json={'draft_id': draft['id'], 'expected_version': row['version'], 'indices': [0]}).json()['resume']['id'] == saved['id']


def test_partial_reply_parser_handles_escapes_and_hides_other_fields():
    result = []; parser = ReplyPreview(result.append)
    text = json.dumps({'reply': '你好\n"引用"😀', 'findings': [{'secret': 'not-for-preview'}]}, ensure_ascii=True)
    for char in text: parser.feed(char)
    assert result[-1] == '你好\n"引用"😀' and all('not-for-preview' not in value for value in result)


def test_provider_sse_reassembles_fragmented_tools_and_usage(setup, monkeypatch):
    app, *_ = setup
    events = [
        {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'call-1', 'type': 'function', 'function': {'name': 'read_', 'arguments': ''}}]}}]},
        {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'name': 'resume', 'arguments': '{}'}}]}, 'finish_reason': 'tool_calls'}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 3}},
    ]
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            for event in events: yield ('data: ' + json.dumps(event) + '\n\n').encode()
            yield b'data: [DONE]\n\n'
    original = httpx.AsyncClient
    monkeypatch.setattr('app.model_transport.httpx.AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Body())), **kwargs))
    result, counts = request_tool_turn(ModelClient(timeout=2), app.state.service.models.resolve('deepseek'), [], [], on_delta=lambda _: None)
    assert result['tool_calls'][0]['function'] == {'name': 'read_resume', 'arguments': '{}'}
    assert counts == {'prompt_tokens': 10, 'completion_tokens': 3}


@pytest.mark.parametrize('mode', ['truncated', 'deadline'])
def test_provider_stream_rejects_incomplete_and_total_deadline(setup, monkeypatch, mode):
    app, *_ = setup
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(5):
                if mode == 'deadline': await asyncio.sleep(.03)
                yield b': keepalive\n\n'
    original = httpx.AsyncClient
    monkeypatch.setattr('app.model_transport.httpx.AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Body())), **kwargs))
    with pytest.raises(httpx.ReadTimeout if mode == 'deadline' else ValueError):
        request_tool_turn(ModelClient(timeout=.05), app.state.service.models.resolve('deepseek'), [], [], on_delta=lambda _: None)
