"""Library deletion is owner-scoped and preserves existing consent/history."""
from test_hiring import scene, apply_body, change
from test_auth_isolation import create_resume, preferences


def test_delete_requires_owner_current_workspace_and_csrf_and_is_idempotent(scene):
    app, recruiter, _, owner, outsider, guest, users, job, resume = scene
    spare = create_resume(owner)
    endpoint = '/resumes/' + resume['id']
    assert guest.delete(endpoint).status_code == 401
    assert outsider.delete(endpoint).status_code == 404
    assert recruiter.delete(endpoint).status_code == 404
    csrf = owner.headers.pop('X-CSRF-Token')
    assert owner.delete(endpoint).status_code == 403
    owner.headers['X-CSRF-Token'] = csrf
    assert owner.delete(endpoint, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert {r['id'] for r in owner.get('/resumes').json()} == {resume['id'], spare['id']}
    assert owner.delete(endpoint).json()['deleted'] is True
    assert owner.delete(endpoint).status_code == 200
    assert [r['id'] for r in owner.get('/resumes').json()] == [spare['id']]
    events = [r for r in app.state.service.db.list('audit_logs', owner=users[2]['actor']) if r['event_type'] == '简历删除']
    assert len(events) == 1 and events[0]['detail']['resume_id'] == resume['id']
    own_recruiter_resume = create_resume(recruiter)
    result = recruiter.post('/auth/workspace', json={'role': 'candidate'})
    recruiter.headers['X-CSRF-Token'] = result.json()['csrf_token']
    assert recruiter.delete('/resumes/' + own_recruiter_resume['id']).status_code == 404


def test_deleted_resume_cannot_start_new_work_but_ai_and_application_history_still_open(scene):
    app, recruiter, _, owner, _, _, users, job, resume = scene
    preferences(owner, 'candidate', resume['id'])
    application = owner.post('/applications', json=apply_body(job, resume, share_preferences=True)).json()
    task = owner.post('/ai/workspaces', json={'resume_id': resume['id'], 'job_id': job['id']})
    assert task.status_code == 200, task.text
    task = task.json()
    # A saved report references the original material, rather than the library list.
    saved = app.state.service.db.insert('fit_reports', {'display_name': resume['display_name']}, users[2]['actor'],
                                        resume['data_origin'], resume_id=resume['id'], job_id=job['id'])
    assert owner.delete('/resumes/' + resume['id']).status_code == 200
    assert owner.get('/resumes').json() == []
    assert owner.post('/ai/workspaces', json={'resume_id': resume['id']}).status_code == 404
    assert owner.post('/fit/analyze', json={'resume_id': resume['id'], 'job_id': job['id']}).status_code == 404
    assert owner.post('/applications', json=apply_body(job, resume)).status_code == 404
    config = owner.get('/config/preferences').json()
    assert owner.post('/preferences/submit', json={'side': 'candidate', 'resume_id': resume['id'],
        'dimensions': {}, 'dimension_version': config['version'], 'share_with_counterparty': True}).status_code == 404
    historical = owner.get('/ai/workspaces/' + task['id'])
    assert historical.status_code == 200 and historical.json()['resume']['text'] == resume['text']
    assert owner.get('/ai/workspaces').json()[0]['id'] == task['id']
    assert any(r['id'] == saved['id'] for r in owner.get('/fit/reports').json())
    assert recruiter.get('/applications/' + application['id']).json()['resume_snapshot']['text'] == resume['text']
    assert owner.get('/applications/' + application['id']).json()['resume_snapshot']['text'] == resume['text']
    withdrawn = change(owner, application, 'withdraw')
    assert withdrawn.status_code == 200, withdrawn.text
    assert recruiter.get('/applications/' + application['id']).json()['resume_snapshot'] is None
    with app.state.service.db.transaction() as cx:
        assert cx.execute('PRAGMA foreign_key_check').fetchall() == []


def test_recruiter_library_deletion_excludes_future_screening_without_touching_other_resumes(scene):
    app, recruiter, _, owner, _, _, users, job, candidate_resume = scene
    removed, retained = create_resume(recruiter), create_resume(recruiter)
    assert recruiter.delete('/resumes/' + removed['id']).status_code == 200
    result = recruiter.post('/batches/run', json={'job_id': job['id']})
    assert result.status_code == 200, result.text
    assert {r['resume_id'] for r in app.state.service.db.list('batches', owner=users[0]['actor'])} == {retained['id']}
    assert recruiter.post('/assessments', json={'job_id': job['id'], 'resume_ids': [removed['id']]}).status_code == 404
    assert owner.get('/resumes').json()[0]['id'] == candidate_resume['id']
