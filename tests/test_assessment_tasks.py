"""Synthetic report jobs: disconnect recovery, deduplication and consent boundaries."""
import threading
import time
from uuid import uuid4
from app.errors import DomainError
from test_hiring import scene, apply_body, change


def material(scene):
    app, recruiter, _, candidate, _, _, _, job, resume = scene
    application = candidate.post('/applications', json=apply_body(job, resume)).json()
    imported = recruiter.post('/applications/' + application['id'] + '/resume-import',
        json={'expected_version': application['version']}).json()['resume']
    body = {'job_id': job['id'], 'resume_ids': [imported['id']], 'request_id': str(uuid4())}
    return app, recruiter, candidate, application, body


def finished(client, id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        row = client.get('/assessment-tasks/' + id).json()
        if row.get('status') not in {'queued', 'running'}: return row
        time.sleep(.01)
    raise AssertionError('synthetic job did not finish')


def test_slow_generation_returns_immediately_and_reconnect_does_not_duplicate(scene, monkeypatch):
    app, client, _, _, body = material(scene)
    gate = threading.Event(); started = threading.Event()
    original = app.state.service.evaluate
    calls = []
    def slow(*args):
        calls.append(1); started.set(); assert gate.wait(3)
        return original(*args)
    monkeypatch.setattr(app.state.service, 'evaluate', slow)
    try:
        start = time.monotonic()
        response = client.post('/assessment-tasks', json=body)
        assert response.status_code == 202 and time.monotonic() - start < 1
        task = response.json(); assert started.wait(1)
        assert client.get('/assessment-tasks/' + task['id']).json()['status'] == 'running'
        assert client.get('/assessment-tasks', params={'job_id': body['job_id']}).json()[0]['id'] == task['id']
        assert client.post('/assessment-tasks', json=body).json()['id'] == task['id']
        assert client.post('/assessment-tasks', json={**body, 'request_id': str(uuid4())}).json()['id'] == task['id']
    finally: gate.set()
    result = finished(client, task['id'])
    assert result['status'] == 'completed' and result['processed'] == 1 and len(result['report_ids']) == 1
    assert result['model']['id'] == 'deepseek' and 'api_key' not in str(result)
    assert client.post('/assessment-tasks', json=body).json()['id'] == task['id']
    assert len(calls) == 1 and len(app.state.service.db.list('ability_reports')) == 1


def test_provider_timeout_is_reported_without_false_success_or_automatic_retry(scene, monkeypatch):
    app, client, _, _, body = material(scene)
    def fail(*args): raise DomainError('AI_PROVIDER_TIMEOUT', 'DeepSeek 响应超时，未生成新报告。', 502)
    monkeypatch.setattr(app.state.service, 'evaluate', fail)
    id = client.post('/assessment-tasks', json=body).json()['id']
    result = finished(client, id)
    assert result['status'] == 'failed' and result['report_ids'] == []
    assert result['errors'][0]['code'] == 'AI_PROVIDER_TIMEOUT'
    assert not app.state.service.db.list('ability_reports')


def test_job_access_csrf_and_owner_isolation(scene):
    app, client, _, _, body = material(scene)
    _, _, other, candidate, _, guest, _, _, _ = scene
    assert client.post('/assessment-tasks', json=body, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    assert candidate.post('/assessment-tasks', json=body).status_code == 403
    assert other.post('/assessment-tasks', json=body).status_code == 404
    assert guest.post('/assessment-tasks', json=body).status_code == 401
    task = client.post('/assessment-tasks', json=body).json()
    result = finished(client, task['id'])
    assert result['status'] == 'completed'
    assert other.get('/assessment-tasks/' + task['id']).status_code == 404
    assert other.get('/assessment-tasks', params={'job_id': body['job_id']}).status_code == 404


def test_withdrawal_during_model_call_prevents_report_and_hides_progress(scene, monkeypatch):
    app, client, candidate, application, body = material(scene)
    original = app.state.service.evaluate
    def withdraw(*args):
        result = original(*args)
        assert change(candidate, application, 'withdraw').status_code == 200
        return result
    monkeypatch.setattr(app.state.service, 'evaluate', withdraw)
    id = client.post('/assessment-tasks', json=body).json()['id']
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        row = app.state.service.db.get('assessment_tasks', id)
        if row['status'] == 'failed': break
        time.sleep(.01)
    assert row['status'] == 'failed' and row['errors'][0]['code'] == 'RESUME_CONSENT_UNAVAILABLE'
    assert app.state.service.db.list('ability_reports') == []
    assert client.get('/assessment-tasks/' + id).status_code == 403
    assert client.get('/assessment-tasks', params={'job_id': body['job_id']}).json() == []


def test_restart_marks_inflight_tasks_interrupted_without_replaying_model(scene):
    app, client, _, _, body = material(scene)
    row = app.state.service.db.insert('assessment_tasks', {**body, 'status': 'running', 'processed': 0,
        'report_ids': [], 'errors': [], 'model': {'id': 'deepseek'}},
        scene[6][0]['actor'], job_id=body['job_id'])
    app.state.report_tasks.recover()
    result = client.get('/assessment-tasks/' + row['id']).json()
    assert result['status'] == 'interrupted' and '重启' in result['message']
    assert not app.state.service.db.list('ability_reports')


def test_executor_reopens_after_application_lifespan_restart(scene):
    app, client, _, _, body = material(scene)
    app.state.report_tasks.close()
    app.state.report_tasks.start()
    response = client.post('/assessment-tasks', json=body)
    assert response.status_code == 202
    assert finished(client, response.json()['id'])['status'] == 'completed'
