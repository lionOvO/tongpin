"""Recruiter workspace tools use saved, authorized evidence, with no model calls."""
from uuid import uuid4
import pytest
from test_recruiter_assistant import chat_scene, send, history
from test_recruiter_review import review_scene
from test_hiring import scene, change


def update(client, row, action, version, **fields):
    return client.post(f"/applications/{row['id']}/recruiter-assistant/workspace", json={
        'action': action, 'expected_version': version, 'request_id': str(uuid4()), **fields})


def test_business_context_plan_and_exact_sources(chat_scene):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = chat_scene
    saved = update(a, row, 'context', 0, business_context='维护订单业务。联系 qa@example.com')
    assert saved.status_code == 200, saved.text
    assert 'qa@example.com' not in saved.json()['business_context'] and not calls
    data = send(a, row, expected_version=1).json()
    message = data['messages'][-1]
    question = {'message_id': message['id'], 'question': message['questions'][0]}
    response = update(a, row, 'plan', 2, questions=[question, question], notes='讨论协作方式，不作为候选人事实。')
    assert response.status_code == 200, response.text
    saved = response.json()
    assert len(saved['plan']) == 1 and saved['plan'][0]['citations'] == message['citations']
    assert saved['notes'] == '讨论协作方式，不作为候选人事实。' and len(calls) == 1
    assert update(a, row, 'plan', 3, questions=[{**question, 'question': '从未建议的追问'}]).status_code == 422
    assert update(a, row, 'context', 0).status_code == 409
    after = a.get('/applications/' + row['id']).json()
    assert after['resume_snapshot']['text'] == row['resume_snapshot']['text']
    assert after['job_snapshot'] == row['job_snapshot'] and after['status'] == row['status']
    assert after['version'] == row['version'] and not after['messages']


def test_new_history_restore_delete_and_lost_ack(chat_scene):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = chat_scene
    first = send(a, row).json()
    key = str(uuid4())
    response = update(a, row, 'new', 1, request_id=key)
    assert response.status_code == 200, response.text
    second = response.json()
    assert not second['messages'] and second['session_id'] != first['session_id'] and len(second['sessions']) == 2
    assert update(a, row, 'new', 1, request_id=key).json() == second
    old = a.get(f"/applications/{row['id']}/recruiter-assistant", params={'session_id': first['session_id']}).json()
    assert old['archived'] and old['messages'] == first['messages'] and old['version'] == 2
    assert a.get('/applications').json()[0]['ai_message_count'] == 2
    assert update(a, row, 'delete', 2, session_id=first['session_id']).status_code == 200
    assert a.get(f"/applications/{row['id']}/recruiter-assistant", params={'session_id': first['session_id']}).status_code == 404
    assert send(a, row, expected_version=3).status_code == 200
    reset = update(a, row, 'delete', 4).json()
    assert reset['messages'] == [] and not reset['plan'] and len(reset['sessions']) == 1


@pytest.mark.parametrize('action', ['context', 'plan', 'new', 'delete'])
def test_workspace_permissions_csrf_and_revocation(chat_scene, action):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = chat_scene
    for client, code in [(b, 404), (c, 403), (d, 403), (guest, 401)]:
        assert update(client, row, action, 0).status_code == code
    assert a.post(f"/applications/{row['id']}/recruiter-assistant/workspace", headers={'X-CSRF-Token': 'wrong'}, json={}).status_code == 403
    assert update(a, row, action, 0, owner='other').status_code == 422
    assert send(a, row).status_code == 200
    assert update(a, row, 'new', 1).status_code == 200
    assert change(c, row, 'withdraw').status_code == 200
    assert update(a, row, action, 2).status_code == 403
    stored = app.state.service.db.get('applications', row['id'])
    assert not stored['recruiter_chat_archives'] and not stored['recruiter_interview_plan'] and not stored['recruiter_interview_notes']


def test_inflight_turn_blocks_workspace_changes(chat_scene, monkeypatch):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = chat_scene
    original = app.state.service.gateway.call
    def gateway(*args, **kwargs):
        for action in ['context', 'plan', 'new', 'delete']:
            assert update(a, row, action, 0).status_code == 409
        return original(*args, **kwargs)
    monkeypatch.setattr(app.state.service.gateway, 'call', gateway)
    assert send(a, row).status_code == 200
