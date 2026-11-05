"""Conversation isolation, durable unread cursors and safe mutation races."""
from uuid import uuid4
from test_hiring import scene, apply_body, change


def send(client, row, text):
    response = client.post('/applications/' + row['id'] + '/messages', json={
        'text': text, 'expected_version': row['version'], 'request_id': str(uuid4())})
    assert response.status_code == 200, response.text
    return response.json()


def accepted(scene):
    _, enterprise, _, candidate, _, _, _, job, resume = scene
    row = candidate.post('/applications', json=apply_body(job,resume)).json()
    assert enterprise.get('/messages/conversations').json() == []
    row = change(enterprise,row,'invite','希望了解你负责的接口开发经历。').json()
    return change(candidate,row,'accept').json()


def test_invitation_unread_is_durable_and_separate_from_business_version(scene):
    _, a, b, c, d, guest, users, job, resume = scene
    row = c.post('/applications', json=apply_body(job,resume)).json()
    row = change(a,row,'invite','希望进一步沟通具体职责。').json()
    assert c.get('/messages/conversations').json()[0]['unread_count'] == 1
    assert a.get('/messages/conversations').json()[0]['unread_count'] == 0
    read = c.post('/messages/conversations/' + row['id'] + '/read',json={
        'message_count':0,'invitation_at':row['invitation']['created_at']}).json()
    assert read['unread_count'] == 0
    assert (read['version'],read['updated_at'],read['events']) == (row['version'],row['updated_at'],row['events'])
    assert c.get('/messages/conversations').json()[0]['unread_count'] == 0
    assert change(c,row,'accept').status_code == 200  # Reading did not cause a stale-version conflict.


def test_read_cursor_does_not_mark_unseen_new_messages_or_move_backwards(scene):
    _, a, _, c, _, _, _, _, _ = scene
    row = accepted(scene)
    row = send(a,row,'第一条沟通消息。')
    row = send(a,row,'第二条沟通消息。')
    assert c.get('/messages/conversations').json()[0]['unread_count'] == 2
    result = c.post('/messages/conversations/' + row['id'] + '/read',json={'message_count':1}).json()
    assert result['unread_count'] == 1
    result = c.post('/messages/conversations/' + row['id'] + '/read',json={'message_count':2}).json()
    assert result['unread_count'] == 0
    assert c.post('/messages/conversations/' + row['id'] + '/read',json={'message_count':0}).json()['unread_count'] == 0
    row = send(c,row,'收到，我们可以进一步了解。')
    assert a.get('/messages/conversations').json()[0]['unread_count'] == 1
    assert c.get('/messages/conversations').json()[0]['unread_count'] == 0


def test_conversation_lists_read_cursors_and_admin_scope_are_isolated(scene):
    _, a, b, c, d, guest, users, job, resume = scene
    row = accepted(scene)
    for outsider in (b,d):
        assert outsider.get('/messages/conversations').json() == []
        assert outsider.post('/messages/conversations/' + row['id'] + '/read',json={'message_count':0}).status_code == 404
    assert guest.get('/messages/conversations').status_code == 401
    assert c.get('/messages/conversations',headers={'X-Session-Scope':'admin'}).status_code == 403
    assert c.post('/messages/conversations/' + row['id'] + '/read',json={'message_count':0},headers={'X-CSRF-Token':'wrong'}).status_code == 403
    assert c.post('/messages/conversations/' + row['id'] + '/read',json={'message_count':1}).status_code == 409
    assert c.post('/messages/conversations/' + row['id'] + '/read',json={'message_count':0,'side':'enterprise'}).status_code == 422


def test_withdrawal_keeps_chat_history_but_removes_shared_material_and_blocks_send(scene):
    app, a, b, c, d, guest, users, job, resume = scene
    row = accepted(scene)
    row = send(a,row,'可以先介绍一下接口设计吗？')
    row = change(c,row,'withdraw').json()
    detail = a.get('/applications/' + row['id']).json()
    assert len(detail['messages']) == 1 and detail['resume_snapshot'] is None
    assert detail['candidate_preferences'] is None
    assert a.get('/messages/conversations').json()[0]['status'] == 'withdrawn'
    assert a.post('/applications/' + row['id'] + '/messages',json={
        'text':'不能继续发送','expected_version':row['version'],'request_id':str(uuid4())}).status_code == 409
    account_id = users[0]['id']
    with app.state.auth.tx() as cx:
        cx.execute('UPDATE accounts SET disabled=1 WHERE id=?',(account_id,))
    # Suspended counterpart data must not reappear in message previews.
    assert a.get('/messages/conversations').status_code == 403


def test_message_preview_never_exposes_internal_review_or_private_source(scene):
    _, a, _, c, _, _, _, _, _ = scene
    row = accepted(scene)
    row = send(a,row,'这是公开给对方的沟通正文。')
    summary = c.get('/messages/conversations').json()[0]
    assert summary['last_message']['text'] == '这是公开给对方的沟通正文。'
    assert not any(key in summary for key in ('owner','candidate_owner','resume_snapshot','candidate_preferences','recruiter_review','message_reads'))


def test_search_finds_old_messages_only_inside_owned_conversations(scene):
    app, a, b, c, d, guest, users, job, resume = scene
    row = accepted(scene)
    row = send(a,row,'历史消息：订单幂等校验。')
    row = send(c,row,'最新消息已经换了话题。')
    for owner in (a,c):
        assert owner.get('/messages/conversations',params={'q':'幂等校验'}).json()[0]['id'] == row['id']
        assert owner.get('/messages/conversations',params={'q':'不存在的关键词'}).json() == []
    for outsider in (b,d):
        assert outsider.get('/messages/conversations',params={'q':'幂等校验'}).json() == []
    assert a.get('/messages/conversations',params={'q':'a'*101}).status_code == 422
    app.state.service.db.update('job_profiles',job['id'],{'moderation_status':'suspended'})
    assert a.get('/messages/conversations',params={'q':'幂等校验'}).json() == []
