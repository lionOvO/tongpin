"""Synthetic, application-scoped recruiter cards; no external model requests."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from app.errors import DomainError
from app.hiring import Hiring
from app.recruiter_review import RecruiterReview, RecruiterReviewInput, ReviewOutput
from app.security import redact
from test_hiring import scene, apply_body, change


@pytest.fixture
def review_scene(scene, monkeypatch):
    app, a, b, c, d, guest, users, job, resume = scene
    row = c.post('/applications', json=apply_body(job, resume)).json()
    svc = app.state.service
    svc.settings.llm_mode = 'live'; svc.settings.api_key = 'synthetic-model-key'
    calls = []
    quote = '主导校园项目，使用 Python 与 FastAPI 构建交易服务。'
    output = {'overview': '简历描述了 Python 与 FastAPI 交易服务项目。', 'overview_quotes': [quote],
        'strengths': [{'title': 'Python 接口开发', 'work': '简历描述主导校园交易服务项目。',
            'evidence_kind': 'experience', 'resume_quote': quote, 'business_link': {
                'task': '后端服务开发', 'reason': '可进一步了解交易服务经历与当前接口任务的关联。',
                'job_quote': redact(job['source_jd']), 'source': 'job'},
            'interview_question': '你在交易服务中实际负责了哪些接口和异常流程？'}],
        'open_questions': [{'topic': '职责与成果', 'question': '项目中你具体完成了哪些交付？'}]}

    def gateway(agent, instructions, value, schema, validate=None, **kwargs):
        calls.append({'agent': agent, 'instructions': instructions, 'value': deepcopy(value), **kwargs})
        result = schema.model_validate(output).model_dump()
        if validate: validate(result)
        return result
    monkeypatch.setattr(svc.gateway, 'call', gateway)
    return (*scene, row, calls, output)


def analyze(a, row, **kwargs):
    return a.post('/applications/' + row['id'] + '/recruiter-review', json={
        'expected_version': row['version'], 'model_id': 'deepseek', **kwargs})


def test_profile_cache_provenance_and_every_application_remains_visible(review_scene):
    app, a, b, c, d, guest, users, job, resume, row, calls, _ = review_scene
    assert a.get('/applications/' + row['id'] + '/recruiter-review').json()['review'] is None
    result = analyze(a, row)
    assert result.status_code == 200, result.text
    card = result.json()['review']
    assert card['strengths'][0]['resume_quote'] in resume['text']
    assert card['model_id'] == 'deepseek' and card['partial'] is False
    assert analyze(a, row).json()['review']['created_at'] == card['created_at']
    assert len(calls) == 1
    assert analyze(a, row, regenerate=True).status_code == 200
    assert len(calls) == 2
    summary = a.get('/applications').json()[0]
    assert summary['review_strengths'] == ['Python 接口开发'] and summary['review_ready']
    assert 'recruiter_review' not in c.get('/applications/' + row['id']).json()
    assert 'review_strengths' not in c.get('/applications').json()[0]
    # Analysis does not mutate status/version, invite or send a message.
    after = a.get('/applications/' + row['id']).json()
    assert after['version'] == row['version'] and after['status'] == 'submitted'
    assert len(after['events']) == 1 and after['messages'] == []
    svc = app.state.service
    svc.settings.llm_mode = 'demo'
    other_resume = d.post('/resumes', json={'name': '第二份合成简历', 'text': '项目：使用 Python 处理数据，负责清洗字段和核对结果。', 'data_origin': 'synthetic'}).json()
    second = d.post('/applications', json=apply_body(job, other_resume)).json()
    svc.settings.llm_mode = 'live'
    assert [r['id'] for r in a.get('/applications').json()] == [second['id'], row['id']]


def test_models_roles_csrf_and_foreign_application_boundaries(review_scene):
    app, a, b, c, d, guest, users, job, resume, row, calls, _ = review_scene
    assert a.get('/recruiter/models').status_code == 200
    assert not any(word in a.get('/recruiter/models').text for word in ['api_key', 'synthetic-model-key', 'base_url'])
    for client, code in [(b, 404), (c, 403), (d, 403), (guest, 401)]:
        assert client.get('/applications/' + row['id'] + '/recruiter-review').status_code == code
        assert analyze(client, row).status_code == code
    assert analyze(a, row, owner=users[1]['actor']).status_code == 422
    assert analyze(a, row, model_id='https://attacker.invalid').status_code == 422
    assert a.post('/applications/' + row['id'] + '/recruiter-review', headers={'X-CSRF-Token': 'wrong'}, json={'expected_version': 1}).status_code == 403
    assert a.get('/recruiter/models', headers={'X-Session-Scope': 'admin'}).status_code == 403
    assert calls == []


def test_only_authorized_snapshots_enter_model_and_business_context_is_distinct(review_scene):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = review_scene
    app.state.service.db.update('resumes', resume['id'], {'text': '修改后私人简历：不可发送给原投递企业。'})
    app.state.service.db.insert('ai_sessions', {'messages': [{'text': '私人 AI 对话不可访问'}]}, users[2]['actor'], resume_id=resume['id'])
    assert analyze(a, row, business_context='维护订单接口。邮箱 example@example.com').status_code == 200
    value = calls[0]['value']
    assert set(value['sources']) == {'resume', 'job', 'business_context'}
    assert '修改后私人简历' not in str(value) and '私人 AI 对话' not in str(value)
    assert users[2]['actor'] not in str(value) and row['candidate_name'] not in str(value)
    assert 'example@example.com' not in str(value)
    assert output['strengths'][0]['resume_quote'] in value['sources']['resume']


@pytest.mark.parametrize('terminal,side', [('withdraw', 'candidate'), ('reject', 'enterprise'), ('decline', 'candidate')])
def test_revoke_also_removes_cards_and_list_strengths(review_scene, terminal, side):
    app, a, b, c, d, guest, users, job, resume, row, calls, _ = review_scene
    assert analyze(a, row).status_code == 200
    if terminal == 'decline': row = change(a, row, 'invite', '进一步了解接口开发。').json()
    response = change(c if side == 'candidate' else a, row, terminal)
    assert response.status_code == 200
    assert a.get('/applications/' + row['id'] + '/recruiter-review').status_code == 403
    assert a.get('/applications').json()[0]['review_strengths'] == []
    assert app.state.service.db.get('applications', row['id'])['recruiter_review'] is None


def test_withdraw_while_model_is_running_prevents_commit(review_scene, monkeypatch):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = review_scene
    def delayed(*args, **kwargs):
        assert change(c, row, 'withdraw').status_code == 200
        return deepcopy(output)
    monkeypatch.setattr(app.state.service.gateway, 'call', delayed)
    response = analyze(a, row)
    assert response.status_code == 403
    stored = app.state.service.db.get('applications', row['id'])
    assert stored['status'] == 'withdrawn' and not stored.get('recruiter_review') and not stored['recruiter_review_running']


def test_session_change_during_request_blocks_card_commit(review_scene, monkeypatch):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = review_scene
    def switched(*args, **kwargs):
        assert a.post('/auth/workspace', json={'role': 'candidate'}).status_code == 200
        return deepcopy(output)
    monkeypatch.setattr(app.state.service.gateway, 'call', switched)
    assert analyze(a, row).status_code in {401, 403}
    stored = app.state.service.db.get('applications', row['id'])
    assert not stored.get('recruiter_review') and stored['recruiter_review_running'] is None


def test_human_progress_change_is_preserved_during_card_generation(review_scene, monkeypatch):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = review_scene
    def invited(*args, **kwargs):
        assert change(a, row, 'invite', '请介绍你负责的接口。').status_code == 200
        return deepcopy(output)
    monkeypatch.setattr(app.state.service.gateway, 'call', invited)
    assert analyze(a, row).status_code == 200
    stored = app.state.service.db.get('applications', row['id'])
    assert stored['status'] == 'invited' and stored['version'] == 2
    assert len(stored['events']) == 2 and stored['recruiter_review']


@pytest.mark.parametrize('bad', ['resume_quote', 'job_quote', 'rating', 'mentioned'])
def test_bad_evidence_or_decisions_preserve_previous_card(review_scene, bad):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = review_scene
    first = analyze(a, row).json()['review']
    if bad == 'resume_quote': output['strengths'][0]['resume_quote'] = '不存在的简历经历'
    if bad == 'job_quote': output['strengths'][0]['business_link']['job_quote'] = '不存在的公司业务'
    if bad == 'rating': output['overview'] = '匹配度 98%'
    if bad == 'mentioned': output['strengths'][0]['evidence_kind'] = 'mentioned'
    assert analyze(a, row, regenerate=True).status_code == 422
    current = a.get('/applications/' + row['id'] + '/recruiter-review').json()
    assert current['review'] == first and not current['running']


def test_provider_failure_unlocks_without_hiding_existing_resume(review_scene, monkeypatch):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = review_scene
    def failed(*args, **kwargs): raise RuntimeError('provider-key-secret')
    monkeypatch.setattr(app.state.service.gateway, 'call', failed)
    response = analyze(a, row)
    assert response.status_code == 502 and 'provider-key-secret' not in response.text
    assert a.get('/applications/' + row['id']).json()['resume_snapshot']
    assert not a.get('/applications/' + row['id'] + '/recruiter-review').json()['running']


def test_update_timeout_retains_old_card_and_allows_a_new_model(review_scene, monkeypatch):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = review_scene
    first = analyze(a, row).json()['review']
    assert calls[0]['timeout'] == 90
    original = app.state.service.gateway.call
    def failed(*args, **kwargs):
        raise DomainError('AI_PROVIDER_TIMEOUT', '所选模型服务响应超时。', 502)
    monkeypatch.setattr(app.state.service.gateway, 'call', failed)
    result = analyze(a, row, regenerate=True)
    assert result.status_code == 502 and result.json()['detail']['code'] == 'AI_PROVIDER_TIMEOUT'
    current = a.get('/applications/' + row['id'] + '/recruiter-review').json()
    assert current['review'] == first and not current['running']
    monkeypatch.setattr(app.state.service.gateway, 'call', original)
    app.state.service.settings.relay_api_key = 'synthetic-relay-key'
    result = analyze(a, row, model_id='relay-gpt-61', regenerate=True)
    assert result.status_code == 200 and result.json()['review']['model_id'] == 'relay-gpt-61'


def test_model_configuration_and_enterprise_revocation(review_scene):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = review_scene
    assert analyze(a, row).status_code == 200
    app.state.service.settings.api_key = ''
    assert analyze(a, row, regenerate=True).status_code == 503
    assert a.get('/applications/' + row['id'] + '/recruiter-review').json()['review']
    with app.state.auth.tx() as cx:
        cx.execute("UPDATE enterprise_submissions SET status='revoked' WHERE account_id=?", (users[0]['id'],))
    assert a.get('/recruiter/models').status_code == 403
    assert a.get('/applications/' + row['id'] + '/recruiter-review').status_code == 403
    assert a.get('/applications').status_code == 403
    assert Hiring(app.state.service, app.state.auth).public(app.state.service.db.get('applications', row['id']), users[0]['actor'])['review_strengths'] == []


def test_owner_concurrency_and_changed_context_require_new_analysis(review_scene, monkeypatch):
    app, a, b, c, d, guest, users, job, resume, row, calls, output = review_scene
    reader = RecruiterReview(Hiring(app.state.service, app.state.auth))
    started, release = Event(), Event()
    def slow(*args, **kwargs):
        started.set(); assert release.wait(10)
        return deepcopy(output)
    monkeypatch.setattr(app.state.service.gateway, 'call', slow)
    data = RecruiterReviewInput(expected_version=1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(reader.analyze, row['id'], data, users[0]['actor'])
        assert started.wait(10)
        try:
            with pytest.raises(DomainError) as exc:
                reader.analyze(row['id'], data, users[0]['actor'])
            assert exc.value.code == 'AI_RATE_LIMIT'
        finally: release.set()
        assert future.result()['review']
    before = app.state.service.db.get('applications', row['id'])['recruiter_review']['input_hash']
    assert analyze(a, row, business_context='维护订单服务与通知任务。').status_code == 200
    assert app.state.service.db.get('applications', row['id'])['recruiter_review']['input_hash'] != before


def test_bounded_materials_and_strict_schema():
    sources, partial = RecruiterReview.sources({'resume_snapshot': {'text': '项目：编写接口。\n' * 5000}, 'job_snapshot': {'text': '岗位维护任务。' * 3000}}, '')
    assert partial and len(sources['resume']) == 30000 and len(sources['job']) == 12000
    with pytest.raises(ValueError): ReviewOutput.model_validate({'ranking': [1, 2]})
