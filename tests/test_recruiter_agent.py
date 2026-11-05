"""Phase three: real graph + HTTP/services, synthetic data, scripted providers."""
import json
import time
from uuid import uuid4
from test_recruiter_assistant import chat_scene, history
from test_recruiter_review import review_scene
from test_material_agent import calls
from test_hiring import scene, change
import pytest

QUOTE = '主导校园项目，使用 Python 与 FastAPI 构建交易服务。'


def path(row): return '/applications/' + row['id'] + '/recruiter-assistant'


def reply(questions=False, **changes):
    value = {'reply': '简历写明使用 Python 与 FastAPI 构建交易服务，可围绕接口职责进一步了解。',
        'kind': 'answer', 'citations': [{'source': 'resume', 'quote': QUOTE}],
        'questions': ['你具体负责哪些接口与异常处理？'] if questions else []}
    value.update(changes)
    return {'role': 'assistant', 'content': json.dumps(value, ensure_ascii=False)}


def script(app, monkeypatch, sequence, stream=False):
    values = iter(sequence); requests = []
    def step(messages, tools, **kwargs):
        requests.append({'messages': json.loads(json.dumps(messages)), 'tools': tools, 'agent': kwargs.get('agent')})
        value = next(values); result = value(messages) if callable(value) else value
        if stream and result.get('content'):
            for index in range(0, len(result['content']), 8): kwargs['on_delta'](result['content'][index:index+8])
        return result
    monkeypatch.setattr(app.state.service.gateway, 'tool_step', step)
    return requests


def send(client, row, stream=False, **changes):
    data = {'agent': True, 'action': 'chat', 'message': '结合当前业务，定位相关经历并准备面试提纲。',
        'business_context': '维护订单接口。', 'expected_version': 0, 'request_id': str(uuid4())}
    data.update(changes)
    return client.post(path(row) + '/turns' + ('/stream' if stream else ''), json=data)


def test_tools_stream_outline_selection_and_no_business_side_effects(chat_scene, monkeypatch):
    app, a, b, c, d, guest, users, job, resume, row, old_calls, _ = chat_scene
    app.state.service.db.update('resumes', resume['id'], {'text': 'PRIVATE-LATEST-RESUME 不得读取'})
    app.state.service.db.insert('ai_sessions', {'messages': [{'text': 'PRIVATE-AI-CHAT'}]}, users[2]['actor'], resume_id=resume['id'])
    requests = script(app, monkeypatch, [calls(('read_application', {}), ('read_job_requirements', {}), ('read_business_context', {})),
        calls(('find_application_evidence', {'query': 'FastAPI'})),
        calls(('prepare_interview_outline', {'resume_quotes': [QUOTE]})), reply(True)], stream=True)
    key = str(uuid4()); response = send(a, row, stream=True, request_id=key)
    assert response.status_code == 200 and response.headers['x-accel-buffering'] == 'no'
    events = [(block.split('\n')[0], json.loads(block.split('data: ')[1])) for block in response.text.split('\n\n') if block.startswith('event:')]
    previews = [v for kind, v in events if kind == 'event: preview']
    assert len(previews) > 1 and len(previews[0]) < len(previews[-1]) and all('citations' not in v for v in previews)
    assert events[-1][0] == 'event: done'
    result = events[-1][1]
    assert result['agent_run']['status'] == 'completed' and len(result['agent_run']['steps']) == 5
    assert all(s['status'] == 'completed' for s in result['agent_run']['steps'])
    assert result['messages'][-1]['questions'] and not result['plan']
    assert not old_calls and all(r['agent'] == 'RecruiterMaterialAgent' for r in requests)
    assert 'sources' not in json.loads(requests[0]['messages'][1]['content'])
    assert all(secret not in json.dumps(requests, ensure_ascii=False) for secret in ['PRIVATE-LATEST-RESUME', 'PRIVATE-AI-CHAT', users[2]['actor']])
    # Preparing a plan did not save it; the existing human selection endpoint does.
    assistant = result['messages'][-1]
    saved = a.post(path(row) + '/workspace', json={'action': 'plan', 'request_id': str(uuid4()), 'expected_version': 1,
        'questions': [{'message_id': assistant['id'], 'question': assistant['questions'][0]}], 'notes': '围绕实际接口职责沟通。'})
    assert saved.status_code == 200 and saved.json()['plan'][0]['citations'] == assistant['citations']
    after = a.get('/applications/' + row['id']).json()
    assert after['status'] == row['status'] and after['version'] == row['version'] and not after['messages']
    assert history(a, row).json()['agent_run']['preview'] == ''
    assert send(a, row, request_id=key).status_code == 200 and len(requests) == 4
    # Counterparties cannot inspect tool progress or recruiter drafts.
    private = c.get('/applications/' + row['id']).json()
    assert 'recruiter_agent_run' not in private


@pytest.mark.parametrize('tool_request', [calls(('read_resume', {'resume_id': 'private'})),
    calls(('read_application', {'application_id': 'foreign'})), calls(('send_invitation', {})),
    calls(('prepare_interview_outline', {'resume_quotes': [QUOTE]}))])
def test_tool_permissions_and_preparation_require_reading(chat_scene, monkeypatch, tool_request):
    app, a, *_ = chat_scene; row = chat_scene[-3]
    script(app, monkeypatch, [tool_request])
    response = send(a, row)
    assert response.status_code == 422
    result = history(a, row).json()
    assert not result['messages'] and not result['plan'] and not result['processing']


@pytest.mark.parametrize('bad', ['unread', 'unprepared', 'business_fact', 'ranking'])
def test_invalid_results_never_commit_and_preview_cleared(chat_scene, monkeypatch, bad):
    app, a, *_ = chat_scene; row = chat_scene[-3]
    output = reply(questions=bad == 'unprepared')
    if bad == 'business_fact': output = reply(citations=[{'source': 'business_context', 'quote': '维护订单接口。'}])
    if bad == 'ranking': output = reply(reply='候选人排名第一，匹配度 99%')
    sequence = [] if bad == 'unread' else [calls(('read_application', {}))]
    script(app, monkeypatch, [*sequence, output, output], stream=True)
    response = send(a, row, stream=True)
    assert 'event: error' in response.text and 'event: done' not in response.text
    result = history(a, row).json()
    assert result['agent_run']['preview'] == '' and not result['processing'] and not result['messages']


def test_cancel_mid_stream_blocks_late_answer_and_allows_retry(chat_scene, monkeypatch):
    app, a, *_ = chat_scene; row = chat_scene[-3]; seen = []
    def cancel(messages):
        current = history(a, row).json(); seen.append(current)
        assert current['processing']
        assert a.post(path(row) + '/cancel', json={'run_id': current['agent_run']['id']}).status_code == 200
        return reply()
    script(app, monkeypatch, [calls(('read_application', {})), cancel], stream=True)
    response = send(a, row, stream=True)
    assert 'AI_CANCELLED' in response.text
    current = history(a, row).json()
    assert current['version'] == 1 and current['agent_run']['status'] == 'cancelled' and not current['messages']
    script(app, monkeypatch, [calls(('read_application', {})), reply()], stream=True)
    assert 'event: done' in send(a, row, stream=True, expected_version=1).text


def test_withdraw_between_tools_clears_progress_and_prevents_more_reads(chat_scene, monkeypatch):
    app, a, b, c, d, guest, users, job, resume, row, *_ = chat_scene
    def withdraw(messages):
        assert change(c, row, 'withdraw').status_code == 200
        return calls(('find_application_evidence', {'query': 'Python'}))
    requests = script(app, monkeypatch, [calls(('read_application', {})), withdraw])
    assert send(a, row).status_code == 403
    stored = app.state.service.db.get('applications', row['id'])
    assert stored['recruiter_agent_run'] is None and not stored['recruiter_chat'] and len(requests) == 2


def test_stream_auth_csrf_foreign_scope_and_loop_bound(chat_scene, monkeypatch):
    app, a, b, c, d, guest, users, job, resume, row, *_ = chat_scene
    assert send(b, row, stream=True).status_code == 404
    assert send(c, row, stream=True).status_code == 403
    assert send(guest, row, stream=True).status_code == 401
    assert a.post(path(row) + '/turns/stream', headers={'X-CSRF-Token': 'wrong'}, json={}).status_code == 403
    def looping(messages):
        value = calls(('read_application', {})); value['tool_calls'][0]['id'] = str(uuid4()); return value
    requests = script(app, monkeypatch, [looping] * 8)
    assert send(a, row).json()['detail']['code'] == 'AI_AGENT_LIMIT' and len(requests) == 6


def test_expired_run_and_archives_do_not_expose_previews(chat_scene, monkeypatch):
    app, a, *_ = chat_scene; row = chat_scene[-3]
    app.state.service.db.update('applications', row['id'], {'recruiter_chat_running': 'old', 'recruiter_chat_until': time.time()-1,
        'recruiter_agent_run': {'id': str(uuid4()), 'status': 'running', 'preview': '未通过校验', 'label': '进行中', 'steps': []}})
    current = history(a, row).json()
    assert current['agent_run']['status'] == 'interrupted' and current['agent_run']['preview'] == ''
    script(app, monkeypatch, [calls(('read_application', {})), reply()])
    completed = send(a, row).json()
    created = a.post(path(row) + '/workspace', json={'action': 'new', 'expected_version': 1, 'request_id': str(uuid4())}).json()
    archived = a.get(path(row), params={'session_id': completed['session_id']}).json()
    assert created['agent_run'] is None and archived['archived'] and archived['agent_run'] is None
