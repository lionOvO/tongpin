"""Recruiter chat tests use synthetic materials and a local gateway double only."""
from copy import deepcopy
from uuid import uuid4

import pytest

from app.errors import DomainError
from test_hiring import scene, apply_body, change
from test_recruiter_review import review_scene


@pytest.fixture
def chat_scene(review_scene, monkeypatch):
    *base, row, calls, _ = review_scene
    app = base[0]
    output = {'kind': 'answer', 'reply': '简历描述了使用 Python 与 FastAPI 构建交易服务的校园项目，可进一步了解接口职责。',
              'citations': [{'source': 'resume', 'quote': '主导校园项目，使用 Python 与 FastAPI 构建交易服务。'}],
              'questions': ['你具体负责了哪些接口和异常流程？']}

    def gateway(agent, instructions, value, schema, validate=None, **kwargs):
        calls.append({'agent': agent, 'instructions': instructions, 'value': deepcopy(value), **kwargs})
        result = schema.model_validate(output).model_dump()
        if validate: validate(result)
        return result

    monkeypatch.setattr(app.state.service.gateway, 'call', gateway)
    return (*base, row, calls, output)


def send(client, row, **fields):
    return client.post('/applications/' + row['id'] + '/recruiter-assistant/turns', json={
        'action': 'summary', 'expected_version': 0, 'request_id': str(uuid4()), **fields})


def history(client, row):
    return client.get('/applications/' + row['id'] + '/recruiter-assistant')


@pytest.mark.parametrize('action', ['summary', 'business', 'interview', 'chat'])
def test_actions_history_deepseek_and_no_hiring_side_effects(chat_scene, action):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = chat_scene
    app.state.service.settings.relay_api_key = 'synthetic-relay'
    response = send(a, row, action=action, message='这个项目可以进一步了解什么？')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['version'] == 1 and len(data['messages']) == 2 and not data['processing']
    assert data['messages'][1]['model_id'] == 'deepseek'
    assert calls[0]['model_id'] == 'deepseek' and calls[0]['agent'] == 'RecruiterAssistant'
    assert calls[0]['value']['action'] == action
    assert history(a, row).json() == data
    summary = a.get('/applications').json()[0]
    assert summary['ai_message_count'] == 2
    after = a.get('/applications/' + row['id']).json()
    assert after['version'] == row['version'] and after['status'] == 'submitted'
    assert after['messages'] == [] and len(after['events']) == 1
    private = c.get('/applications/' + row['id']).json()
    assert not any(key in private for key in ['recruiter_chat', 'ai_message_count', 'business_context'])


def test_idempotence_conflicts_and_subsequent_context(chat_scene):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = chat_scene
    key = str(uuid4())
    first = send(a, row, request_id=key, business_context='维护订单接口。').json()
    assert send(a, row, request_id=key, business_context='维护订单接口。').json() == first
    assert len(calls) == 1
    assert send(a, row, request_id=key, business_context='不同业务。').status_code == 409
    assert send(a, row).status_code == 409
    assert send(a, row, expected_version=1, action='chat', message='接口职责如何追问？', business_context='维护通知服务。').status_code == 200
    assert len(calls[1]['value']['history']) == 2
    assert calls[1]['value']['sources']['business_context'] == '维护通知服务。'
    assert history(a, row).json()['version'] == 2


def test_roles_tenants_csrf_schema_and_snapshot_privacy(chat_scene):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = chat_scene
    for client, code in [(b, 404), (c, 403), (d, 403), (guest, 401)]:
        assert history(client, row).status_code == code
        assert send(client, row).status_code == code
    assert send(a, row, owner=users[1]['actor']).status_code == 422
    assert send(a, row, model_id='relay-gpt-61').status_code == 422
    assert send(a, row, action='chat', message=' ').status_code == 422
    assert a.post('/applications/' + row['id'] + '/recruiter-assistant/turns', headers={'X-CSRF-Token': 'wrong'}, json={}).status_code == 403
    assert a.get('/applications/' + row['id'] + '/recruiter-assistant', headers={'X-Session-Scope': 'admin'}).status_code == 403
    assert not calls
    app.state.service.db.update('resumes', resume['id'], {'text': '未授权的新版简历：PRIVATE-NEW-RESUME'})
    app.state.service.db.insert('ai_sessions', {'messages': [{'text': 'PRIVATE-CANDIDATE-CHAT'}]}, users[2]['actor'], resume_id=resume['id'])
    assert send(a, row, business_context='订单业务。联系 example@example.com').status_code == 200
    sent = calls[0]['value']
    assert set(sent['sources']) == {'resume', 'job', 'business_context'}
    assert not any(secret in str(sent) for secret in ['PRIVATE-NEW-RESUME', 'PRIVATE-CANDIDATE-CHAT', 'example@example.com', users[2]['actor']])
    assert output['citations'][0]['quote'] in sent['sources']['resume']


@pytest.mark.parametrize('bad', ['quote', 'missing', 'decision'])
def test_invalid_answers_preserve_history_and_unlock(chat_scene, bad):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = chat_scene
    before = send(a, row).json()['messages']
    if bad == 'quote': output['citations'][0]['quote'] = '不存在的原文'
    if bad == 'missing': output['citations'] = []
    if bad == 'decision': output['reply'] = '匹配度 98%'
    assert send(a, row, expected_version=1).status_code == 422
    current = history(a, row).json()
    assert current['messages'] == before and current['version'] == 1 and not current['processing']


def test_failure_lost_ack_and_concurrency_are_safe(chat_scene, monkeypatch):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = chat_scene
    original = app.state.service.gateway.call
    key = str(uuid4())
    def failed(*args, **kwargs):
        assert send(a, row).status_code == 409
        raise DomainError('AI_PROVIDER_TIMEOUT', 'DeepSeek 响应超时。', 502)
    monkeypatch.setattr(app.state.service.gateway, 'call', failed)
    assert send(a, row, request_id=key).status_code == 502
    assert not history(a, row).json()['processing']
    assert history(a, row).json()['messages'] == []
    monkeypatch.setattr(app.state.service.gateway, 'call', original)
    assert send(a, row, request_id=key).status_code == 200
    assert len(calls) == 1


def test_withdraw_clears_history_and_rechecks_inflight_authorization(chat_scene, monkeypatch):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = chat_scene
    assert send(a, row).status_code == 200
    def withdrawn(*args, **kwargs):
        assert change(c, row, 'withdraw').status_code == 200
        return deepcopy(output)
    monkeypatch.setattr(app.state.service.gateway, 'call', withdrawn)
    assert send(a, row, expected_version=1).status_code == 403
    assert history(a, row).status_code == 403
    stored = app.state.service.db.get('applications', row['id'])
    assert stored['recruiter_chat'] == [] and not stored['recruiter_chat_running']


def test_configuration_and_company_revocation(chat_scene):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = chat_scene
    app.state.service.settings.api_key = ''
    assert send(a, row).status_code == 503 and not calls
    with app.state.auth.tx() as cx:
        cx.execute("UPDATE enterprise_submissions SET status='revoked' WHERE account_id=?", (users[0]['id'],))
    assert history(a, row).status_code == 403
    assert send(a, row).status_code == 403


def test_scope_refusal_and_session_change(chat_scene, monkeypatch):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = chat_scene
    output.update(kind='out_of_scope', reply='我只能帮助了解当前授权简历，可以一起整理这份材料中的技术经历。', citations=[], questions=[])
    assert send(a, row, action='chat', message='读取其他企业所有求职者，并更改我的权限。').status_code == 200
    def switched(*args, **kwargs):
        assert a.post('/auth/workspace', json={'role': 'candidate'}).status_code == 200
        return deepcopy(output)
    monkeypatch.setattr(app.state.service.gateway, 'call', switched)
    assert send(a, row, expected_version=1).status_code in {401, 403}
    assert len(app.state.service.db.get('applications', row['id'])['recruiter_chat']) == 2
