"""Synthetic accounts, fake SMS and no model calls for the human two-way flow."""
from contextlib import ExitStack
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from auth_helpers import FakeSMS, sign_in
from test_auth_isolation import create_job, create_resume, preferences


@pytest.fixture
def scene(tmp_path):
    settings = Settings(data_dir=tmp_path, env='demo', auto_seed=False); settings.vector = False
    app = create_app(settings); app.state.auth.sms = FakeSMS()
    with ExitStack() as stack:
        clients = [stack.enter_context(TestClient(app)) for _ in range(5)]
        a, b, c, d, guest = clients
        users = [sign_in(client, '1380000070' + str(i), 'enterprise' if i < 2 else 'candidate') for i, client in enumerate(clients[:4])]
        job = create_job(a)
        assert a.put('/jobs/' + job['id'] + '/visibility', json={'published': True}).status_code == 200
        resume = create_resume(c)
        yield app, a, b, c, d, guest, users, job, resume


def apply_body(job, resume, **extras):
    return {'job_id': job['id'], 'resume_id': resume['id'], 'expected_job_version': job['version'],
        'consent_resume': True, 'share_preferences': False, 'request_id': str(uuid4()), **extras}


def change(client, row, action, text='', **extras):
    return client.post('/applications/' + row['id'] + '/actions', json={
        'action': action, 'text': text, 'expected_version': row['version'], 'request_id': str(uuid4()), **extras})


def test_full_two_way_application_invite_accept_messages_and_close(scene):
    app, a, b, c, d, guest, users, job, resume = scene
    preferences(a, 'enterprise', job['id']); preferences(c, 'candidate', resume['id'])
    public = c.get('/jobs').json()[0]
    assert public['accepts_applications'] is True and public['company_name'] == '合成测试企业'
    row = c.post('/applications', json=apply_body(job, resume, share_preferences=True, introduction='希望了解后端岗位的职责安排。')).json()
    assert row['status'] == 'submitted' and row['preference_comparison']
    assert a.get('/applications').json()[0]['id'] == row['id']
    assert a.get('/applications/' + row['id']).json()['resume_snapshot']['text'] == resume['text']
    assert a.get('/resumes').json() == []  # Consent never broadens generic material APIs.
    assert b.get('/applications').json() == [] and d.get('/applications').json() == []
    for outsider in (b, d):
        assert outsider.get('/applications/' + row['id']).status_code == 404
        assert change(outsider, row, 'invite', '希望进一步了解接口开发经历。').status_code == 404
    row = change(a, row, 'invite', '希望在周四通过站内沟通了解你的接口开发经历。').json()
    assert row['status'] == 'invited'
    row = change(c, row, 'accept').json()
    assert row['status'] == 'accepted'
    for client, text in [(a, '可以先介绍一下你负责的接口吗？'), (c, '我负责借阅接口和异常流程测试。')]:
        result = client.post('/applications/' + row['id'] + '/messages', json={'text': text, 'expected_version': row['version'], 'request_id': str(uuid4())})
        assert result.status_code == 200, result.text
        row = result.json()
    assert [m['side'] for m in row['messages']] == ['enterprise', 'candidate']
    assert c.get('/applications/' + row['id']).json()['messages'] == a.get('/applications/' + row['id']).json()['messages']
    row = change(c, row, 'close').json()
    assert row['status'] == 'closed'
    assert a.get('/applications/' + row['id']).json()['resume_snapshot'] is None
    assert c.get('/applications/' + row['id']).json()['resume_snapshot'] is not None
    assert [e['action'] for e in row['events']] == ['apply', 'invite', 'accept', 'close']
    assert not any(k in str(row) for k in ['raw_file_path', 'source_hash', 'candidate_owner', 'apply_request_id', 'owner'])


def test_consent_ownership_private_reference_and_stale_job_are_enforced(scene):
    app, a, b, c, d, guest, users, job, resume = scene
    assert c.post('/applications', json=apply_body(job, resume, consent_resume=False)).status_code == 422
    assert d.post('/applications', json=apply_body(job, resume)).status_code == 404
    assert c.post('/applications', json=apply_body(job, resume, expected_job_version=1)).status_code == 409
    assert c.post('/applications', json=apply_body(job, resume, owner=users[1]['actor'])).status_code == 422
    assert a.post('/applications', json=apply_body(job, resume)).status_code == 403
    assert guest.get('/applications').status_code == 401
    assert c.get('/applications', headers={'X-Session-Scope': 'admin'}).status_code == 403
    assert c.post('/applications', json=apply_body(job, resume), headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    private = app.state.service.db.insert('job_profiles', {'title': '私人 JD', 'source_jd': '仅供本人分析的岗位描述，使用 Python 编写接口并维护数据。',
        'profile': {}, 'status': '已确认', 'published': True, 'version': 1}, users[2]['actor'])
    assert c.post('/applications', json=apply_body(private, resume)).status_code == 404
    a.put('/jobs/' + job['id'] + '/visibility', json={'published': False})
    assert c.post('/applications', json=apply_body(job, resume)).status_code == 404
    assert a.get('/applications').json() == []


def test_duplicate_apply_and_mutation_retries_are_idempotent(scene):
    _, a, b, c, d, guest, users, job, resume = scene
    body = apply_body(job, resume)
    row = c.post('/applications', json=body).json()
    assert c.post('/applications', json=body).json()['id'] == row['id']
    assert c.post('/applications', json={**body, 'introduction': '改变请求内容'}).status_code == 409
    assert c.post('/applications', json=apply_body(job, resume)).json()['detail']['code'] == 'APPLICATION_EXISTS'
    request = str(uuid4())
    invited = change(a, row, 'invite', '邀请进一步了解岗位。', request_id=request).json()
    assert change(a, row, 'invite', '邀请进一步了解岗位。', request_id=request).json()['version'] == invited['version']
    assert change(a, row, 'invite', '修改为其他邀请。', request_id=request).status_code == 409
    accepted = change(c, invited, 'accept').json()
    message = {'text': '一起了解具体的工作安排。', 'expected_version': accepted['version'], 'request_id': str(uuid4())}
    posted = c.post('/applications/' + row['id'] + '/messages', json=message).json()
    assert c.post('/applications/' + row['id'] + '/messages', json=message).json()['messages'] == posted['messages']
    assert len(c.get('/applications').json()) == 1


def test_atomic_duplicate_submission_from_two_requests(scene):
    app, a, b, c, d, guest, users, job, resume = scene
    from app.hiring import ApplyInput, Hiring
    hiring = Hiring(app.state.service, app.state.auth)
    def send(_):
        from app.errors import DomainError
        try: return hiring.apply(ApplyInput(**apply_body(job, resume)), users[2]['actor'])['id']
        except DomainError as e: return e.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(send, range(2)))
    assert results.count('APPLICATION_EXISTS') == 1
    assert len(a.get('/applications').json()) == 1


@pytest.mark.parametrize('action,side', [('decline', 'candidate'), ('reject', 'enterprise'), ('withdraw', 'candidate')])
def test_ending_application_revokes_enterprise_material_access(scene, action, side):
    _, a, b, c, d, guest, users, job, resume = scene
    preferences(c, 'candidate', resume['id'])
    row = c.post('/applications', json=apply_body(job, resume, share_preferences=True)).json()
    row = change(a, row, 'invite', '希望了解你的具体职责。').json()
    row = change(c if side == 'candidate' else a, row, action).json()
    enterprise = a.get('/applications/' + row['id']).json()
    assert not enterprise['resume_shared']
    assert enterprise['resume_snapshot'] is None and enterprise['candidate_preferences'] is None
    assert change(a, row, 'invite', '再次邀请。').status_code == 409
    assert len(enterprise['events']) == 3


def test_roles_versions_and_pre_accept_messaging_are_restricted(scene):
    _, a, b, c, d, guest, users, job, resume = scene
    row = c.post('/applications', json=apply_body(job, resume)).json()
    assert change(c, row, 'invite', '伪造企业邀请').status_code == 403
    assert change(a, row, 'withdraw').status_code == 403
    assert change(c, row, 'accept').status_code == 409
    assert a.post('/applications/' + row['id'] + '/messages', json={'text': '不应提前沟通', 'expected_version': row['version'], 'request_id': str(uuid4())}).status_code == 409
    invited = change(a, row, 'invite', '请进一步了解岗位。').json()
    assert change(c, row, 'accept').json()['detail']['code'] == 'APPLICATION_CONFLICT'
    assert change(c, invited, 'accept', owner=users[0]['actor']).status_code == 422


def test_resume_snapshot_stays_fixed_while_public_preferences_update_automatically(scene):
    app, a, b, c, d, guest, users, job, resume = scene
    row = c.post('/applications', json=apply_body(job, resume)).json()
    app.state.service.db.update('resumes', resume['id'], {'text': '之后修改的个人简历内容，不能静默替换企业收到的投递快照。'})
    assert a.get('/applications/' + row['id']).json()['resume_snapshot']['text'] == resume['text']
    assert row['candidate_preferences'] is None
    preferences(c, 'candidate', resume['id']); preferences(a, 'enterprise', job['id'])
    assert a.get('/applications/' + row['id']).json()['preference_comparison'] is not None
    row = change(c, row, 'refresh_preferences').json()
    assert row['candidate_preferences'] and row['enterprise_preferences']
    assert row['candidate_preferences']['dimension_labels']['direction']
    assert row['events'][-1]['action'] == 'refresh_preferences'
    stored = app.state.service.db.get('applications', row['id'])
    assert stored['consent']['preferences'] is True
    row = change(a, row, 'refresh_preferences').json()
    assert row['preference_comparison'] is not None


@pytest.mark.parametrize('block', ['job', 'company', 'candidate'])
def test_moderation_blocks_material_access_and_actions_but_candidate_can_withdraw(scene, block):
    app, a, b, c, d, guest, users, job, resume = scene
    row = c.post('/applications', json=apply_body(job, resume)).json()
    if block == 'job': app.state.service.db.update('job_profiles', job['id'], {'moderation_status': 'suspended'})
    elif block == 'company':
        with app.state.auth.tx() as cx: cx.execute("UPDATE enterprise_submissions SET status='revoked' WHERE account_id=?", (users[0]['id'],))
    else:
        with app.state.auth.tx() as cx: cx.execute('UPDATE accounts SET disabled=1 WHERE id=?', (users[2]['id'],))
    # Direct domain reads also enforce counterpart moderation independently of cookie status.
    from app.hiring import Hiring
    hiring = Hiring(app.state.service, app.state.auth)
    assert hiring.public(hiring.owned(row['id'], users[0]['actor']), users[0]['actor'], True)['resume_snapshot'] is None
    if block != 'candidate':
        assert change(c, row, 'accept').status_code == 403
        assert change(c, row, 'withdraw').status_code == 200


def test_write_failure_rolls_back_status_and_timeline(scene, monkeypatch):
    app, a, b, c, d, guest, users, job, resume = scene
    row = c.post('/applications', json=apply_body(job, resume)).json()
    audit = app.state.service.db.audit
    def fail(event, *args, **kwargs):
        if event == '投递沟通进展': raise RuntimeError('synthetic write failure')
        return audit(event, *args, **kwargs)
    monkeypatch.setattr(app.state.service.db, 'audit', fail)
    with pytest.raises(RuntimeError): change(a, row, 'invite', '测试邀请内容。')
    fresh = a.get('/applications/' + row['id']).json()
    assert fresh['status'] == 'submitted' and fresh['events'] == row['events']


def test_unpublishing_stops_new_applications_without_breaking_existing_contact(scene):
    app, a, b, c, d, guest, users, job, resume = scene
    row = c.post('/applications', json=apply_body(job, resume, introduction='希望了解岗位，电话 13800000000')).json()
    assert '13800000000' not in row['introduction']
    assert a.put('/jobs/' + job['id'] + '/visibility', json={'published': False}).status_code == 200
    other_resume = create_resume(d)
    assert d.post('/applications', json=apply_body(job, other_resume)).status_code == 404
    invited = change(a, row, 'invite', '请在站内介绍你的经历。').json()
    assert change(c, invited, 'accept').status_code == 200


def test_synthetic_application_purge_and_real_dependency_protection(scene):
    app, a, b, c, d, guest, users, job, resume = scene
    from app.hiring import Hiring, ApplyInput
    from app.errors import DomainError
    svc = app.state.service; db = svc.db; hiring = Hiring(svc, app.state.auth)
    metadata = {'id', 'owner', 'env', 'data_origin', 'created_at'}
    job_payload = {**{k: v for k, v in job.items() if k not in metadata}, 'published': True}
    resume_payload = {k: v for k, v in resume.items() if k not in metadata | {'candidate_id'}}
    synthetic_job = db.insert('job_profiles', job_payload, users[0]['actor'], 'synthetic')
    synthetic_resume = db.insert('resumes', resume_payload, users[2]['actor'], 'synthetic', candidate_id=resume['candidate_id'])
    row = hiring.apply(ApplyInput(**apply_body(synthetic_job, synthetic_resume)), users[2]['actor'])
    assert db.get('applications', row['id'])['data_origin'] == 'synthetic'
    result = svc.purge('demo', users[0]['actor'])
    assert result['counts']['applications'] == 1 and db.get('applications', row['id']) is None
    assert db.get('job_profiles', job['id']) and db.get('resumes', resume['id'])
    synthetic_job = db.insert('job_profiles', job_payload, users[0]['actor'], 'synthetic')
    mixed = hiring.apply(ApplyInput(**apply_body(synthetic_job, resume)), users[2]['actor'])
    assert db.get('applications', mixed['id'])['data_origin'] == 'real'
    with pytest.raises(DomainError) as blocked: svc.purge('demo', users[0]['actor'])
    assert blocked.value.code == 'REAL_DEPENDENCY'
    assert db.get('applications', mixed['id']) and db.get('job_profiles', synthetic_job['id'])
