"""Real LangGraph + HTTP routes, synthetic accounts, scripted model; no paid requests."""
import json
import time
import httpx
import pytest
from test_ai_workspace import setup, TEXT, PATH
from app.model_transport import request_tool_turn, request_json
from app.model_catalog import ModelProfile
from app.errors import DomainError


def calls(*items):
    return {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': f'call-{name}-{index}', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}
        for index, (name, args) in enumerate(items)]}


def answer(source='R3', quote='负责接口编写和测试', rewrites=False):
    obj = {'reply': '已根据当前材料整理项目职责。草稿需要你核对后保存。',
        'findings': [{'topic': '接口开发', 'status': 'supported', 'observation': '材料写明接口编写及测试。',
                      'advice': '可按实际职责核对表达。', 'citations': [{'source_id': source, 'quote': quote}]}],
        'questions': [], 'rewrites': []}
    if rewrites:
        before = TEXT.splitlines()[-1]
        obj['rewrites'] = [{'source_id': source, 'before': before,
            'after': '项目：使用 Python 开发图书借阅服务；负责接口编写及测试。',
            'reason': '突出本人负责的工作。', 'citations': [{'source_id': source, 'quote': before}]}]
    return {'role': 'assistant', 'content': json.dumps(obj, ensure_ascii=False)}


def script(app, monkeypatch, sequence):
    requests = []; sequence = iter(sequence)
    def step(messages, tools, **kwargs):
        requests.append(json.loads(json.dumps(messages)))
        value = next(sequence)
        return value(messages) if callable(value) else value
    monkeypatch.setattr(app.state.service.gateway, 'tool_step', step)
    return requests


def send(first, session, action='chat', message='帮我整理这段项目并生成表达优化草稿。'):
    return first.post(f"{PATH}/{session['id']}/turns", json={'action': action, 'message': message,
        'expected_version': session['version'], 'agent': True})


def test_agent_finds_experience_prepares_draft_and_only_confirmation_saves(setup, monkeypatch):
    app, first, _, user, _, resume, session = setup
    requests = script(app, monkeypatch, [calls(('find_experience', {'query': 'Python'})),
        calls(('prepare_draft', {'source_ids': ['R3']})), answer(rewrites=True)])
    result = send(first, session)
    assert result.status_code == 200, result.text
    row = result.json(); run = row['agent_run']
    assert run['engine'] == 'langgraph' and run['status'] == 'completed'
    assert [s['tool'] for s in run['steps']] == ['find_experience', 'prepare_draft']
    assert all(s['status'] == 'completed' for s in run['steps'])
    assert len(first.get('/resumes').json()) == 1
    assert app.state.service.db.get('resumes', resume['id'])['text'] == TEXT
    assert not any(secret in str(requests) for secret in [user['actor'], 'fake-key-only', resume['id']])
    draft = row['drafts'][-1]
    saved = first.post(f"{PATH}/{row['id']}/drafts/confirm", json={'draft_id': draft['id'], 'expected_version': row['version']})
    assert saved.status_code == 200, saved.text
    assert saved.json()['resume']['parent_resume_id'] == resume['id']
    assert len(first.get('/resumes').json()) == 2
    assert first.get(f"{PATH}/{row['id']}").json()['agent_run']['status'] == 'completed'


def test_selected_job_and_confirmed_notes_are_scoped_and_redacted(setup, monkeypatch):
    app, first, _, _, _, resume, _ = setup
    jd = '岗位职责：Python 接口开发与自动化测试。联系13800000988，邮箱hiring@example.com。'
    row = first.post(PATH, json={'resume_id': resume['id'], 'jd': jd, 'title': '合成岗位'}).json()
    row = first.post(f"{PATH}/{row['id']}/additions", json={'text': '我负责过异常接口测试与日志排查。', 'expected_version': row['version']}).json()
    requests = script(app, monkeypatch, [calls(('read_resume', {}), ('read_job', {})), answer()])
    result = send(first, row, 'analyze', '')
    assert result.status_code == 200, result.text
    material_results = [json.loads(m['content']) for m in requests[-1] if m['role'] == 'tool']
    assert any(s['kind'] == 'supplement' and s['user_confirmed'] for r in material_results for s in r['sources'])
    assert any(s['kind'] == 'job' for r in material_results for s in r['sources'])
    assert '13800000988' not in str(requests) and 'hiring@example.com' not in str(requests)


@pytest.mark.parametrize('tool,args,code', [
    ('delete_resume', {}, 'AI_AGENT_TOOL_DENIED'),
    ('read_resume', {'resume_id': 'another-user-resume'}, 'AI_AGENT_TOOL_ARGUMENTS'),
    ('prepare_draft', {'source_ids': ['R3']}, 'AI_AGENT_DRAFT_SCOPE'),
])
def test_unopened_tools_and_foreign_arguments_never_execute(setup, monkeypatch, tool, args, code):
    app, first, second, _, _, resume, row = setup
    script(app, monkeypatch, [calls((tool, args))])
    assert send(second, row).status_code == 404
    result = send(first, row)
    assert result.status_code == 422 and result.json()['detail']['code'] == code
    fresh = first.get(f"{PATH}/{row['id']}").json()
    assert fresh['agent_run']['status'] == 'failed' and not fresh['messages'] and not fresh['drafts']
    assert app.state.service.db.get('resumes', resume['id'])['text'] == TEXT


@pytest.mark.parametrize('bad', ['citation', 'unprepared', 'new_number', 'unread'])
def test_final_result_must_pass_existing_evidence_checks(setup, monkeypatch, bad):
    app, first, _, _, _, _, row = setup
    if bad == 'citation': final = answer(quote='不存在的业绩与职责')
    elif bad == 'unread': final = answer(source='R999')
    else:
        final = answer(rewrites=True)
        if bad == 'new_number':
            obj = json.loads(final['content']); obj['rewrites'][0]['after'] += '，性能提升99倍。'
            final['content'] = json.dumps(obj)
    sequence = [calls(('read_resume', {}))]
    if bad == 'new_number': sequence.append(calls(('prepare_draft', {'source_ids': ['R3']})))
    script(app, monkeypatch, [*sequence, final, final])
    result = send(first, row)
    assert result.status_code == 422 and result.json()['detail']['code'] == 'AI_AGENT_VALIDATION', result.text
    fresh = first.get(f"{PATH}/{row['id']}").json()
    assert not fresh['messages'] and not fresh['drafts']


def test_cancellation_and_stale_cancel_cannot_publish_result(setup, monkeypatch):
    app, first, second, _, _, _, row = setup
    def cancel(messages):
        fresh = first.get(f"{PATH}/{row['id']}").json()
        run_id = fresh['agent_run']['id']
        assert second.post(f"{PATH}/{row['id']}/cancel", json={'run_id': run_id}).status_code == 404
        assert first.post(f"{PATH}/{row['id']}/cancel", json={'run_id': 'old-run'}).status_code == 409
        assert first.post(f"{PATH}/{row['id']}/cancel", json={'run_id': run_id}).json()['agent_run']['status'] == 'cancelled'
        return answer()
    script(app, monkeypatch, [cancel])
    result = send(first, row)
    assert result.status_code == 409 and result.json()['detail']['code'] == 'AI_CANCELLED'
    fresh = first.get(f"{PATH}/{row['id']}").json()
    assert fresh['agent_run']['status'] == 'cancelled' and not fresh['messages'] and not fresh['processing']


def test_rechecks_job_visibility_after_provider_returns(setup, monkeypatch):
    app, first, _, _, _, resume, _ = setup
    row = first.post(PATH, json={'resume_id': resume['id'], 'jd': '岗位职责：使用 Python 编写后端接口和测试，参与业务需求讨论。', 'title': '岗位'}).json()
    def hide(messages):
        with app.state.service.db.transaction() as cx:
            cx.execute("UPDATE job_profiles SET owner=? WHERE id=?", ('enterprise:other', row['job_id']))
        return calls(('read_resume', {}))
    requests = script(app, monkeypatch, [hide])
    result = send(first, row)
    assert result.status_code == 409 and result.json()['detail']['code'] == 'AI_JOB_UNAVAILABLE'
    assert len(requests) == 1
    saved = app.state.service.db.get('ai_sessions', row['id'])
    assert not saved['messages'] and not saved['running']


def test_loop_limit_is_bounded_and_failed_run_can_retry(setup, monkeypatch):
    app, first, _, _, _, _, row = setup
    sequence = [calls(('read_resume', {})) for _ in range(7)]
    for i, step in enumerate(sequence): step['tool_calls'][0]['id'] = f'unique-{i}'
    requests = script(app, monkeypatch, sequence)
    result = send(first, row)
    assert result.status_code == 422 and result.json()['detail']['code'] == 'AI_AGENT_LIMIT'
    assert len(requests) == 6
    script(app, monkeypatch, [calls(('read_resume', {})), answer()])
    assert send(first, row).status_code == 200


def test_expired_execution_is_visible_and_can_be_retried(setup, monkeypatch):
    app, first, _, _, _, _, row = setup
    app.state.service.db.update('ai_sessions', row['id'], {'running': 'dead-worker', 'running_until': time.time()-1,
        'agent_run': {'id': 'dead-worker', 'status': 'running', 'label': '处理中', 'steps': [], 'engine': 'langgraph'}})
    fresh = first.get(f"{PATH}/{row['id']}").json()
    assert fresh['agent_run']['status'] == 'interrupted' and not fresh['processing']
    script(app, monkeypatch, [calls(('read_resume', {})), answer()])
    assert send(first, fresh).status_code == 200


def test_transport_tool_messages_and_audited_gateway_preserve_json_report_path(setup, monkeypatch):
    app, *_ = setup
    payloads = []
    def post(self, url, headers, json):
        payloads.append(json)
        msg = calls(('read_resume', {}))
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'choices': [{'message': msg, 'finish_reason': 'tool_calls'}], 'usage': {'prompt_tokens': 12, 'completion_tokens': 4}})
    monkeypatch.setattr('app.model_transport.ModelClient.post', post)
    messages = [{'role': 'user', 'content': 'synthetic material'}]
    result = app.state.service.gateway.tool_step(messages, [], model_id='deepseek', timeout=1)
    assert result['tool_calls'][0]['function']['name'] == 'read_resume'
    assert 'response_format' not in payloads[0] and payloads[0]['tool_choice'] == 'auto'
    logs = app.state.service.db.list('audit_logs')
    log = next(r for r in logs if r['event_type'] == 'Agent 调用')['detail']
    assert log['agent'] == 'CandidateMaterialAgent' and log['usage']['prompt_tokens'] == 12
    assert 'synthetic material' not in str(log)
    from app.model_transport import ModelClient
    profile = app.state.service.models.resolve('deepseek')
    with pytest.raises(ValueError): request_json(ModelClient(), profile, 'JSON', {}, 100)


def test_graph_provider_calls_are_audited_under_request_owner(setup, monkeypatch):
    app, first, _, user, _, _, row = setup
    values = iter([calls(('read_resume', {})), answer()])
    def post(self, url, headers, json):
        msg = next(values)
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'choices': [{'message': msg, 'finish_reason': 'tool_calls' if msg.get('tool_calls') else 'stop'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 50}})
    monkeypatch.setattr('app.model_transport.ModelClient.post', post)
    result = send(first, row, 'analyze', '')
    assert result.status_code == 200, result.text
    logs = [r for r in app.state.service.db.list('audit_logs') if r['event_type'] == 'Agent 调用']
    assert len(logs) == 2 and all(r['owner'] == user['actor'] for r in logs)
    assert all(r['detail']['agent'] == 'CandidateMaterialAgent' for r in logs)
    assert '图书借阅' not in str(logs) and 'synthetic-only' not in str(logs)


def test_final_validation_can_correct_once_without_losing_tool_context(setup, monkeypatch):
    app, first, _, _, _, _, row = setup
    requests = script(app, monkeypatch, [calls(('read_resume', {})), answer(quote='原文不存在的成果'), answer()])
    result = send(first, row, 'analyze', '')
    assert result.status_code == 200, result.text
    assert len(requests) == 3
    assert any(m['role'] == 'tool' for m in requests[-1])


def test_total_deadline_and_repeated_call_ids_stop_without_writes(setup, monkeypatch):
    from types import SimpleNamespace
    import app.material_agent as agent
    app, first, _, _, _, _, row = setup
    clock = [0]
    monkeypatch.setattr(agent, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    def delayed(messages):
        clock[0] = 121
        return calls(('read_resume', {}))
    script(app, monkeypatch, [delayed])
    result = send(first, row)
    assert result.status_code == 504 and result.json()['detail']['code'] == 'AI_AGENT_DEADLINE'
    assert not first.get(f"{PATH}/{row['id']}").json()['messages']
    clock[0] = 0
    script(app, monkeypatch, [calls(('read_resume', {})), calls(('read_resume', {}))])
    result = send(first, row)
    assert result.status_code == 422 and result.json()['detail']['code'] == 'AI_AGENT_TOOL_DENIED'
