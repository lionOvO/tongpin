"""Import/download only immutable, authorized application snapshots (synthetic fixtures)."""
from concurrent.futures import ThreadPoolExecutor
from app.hiring import ApplicationResumeImport, Hiring
from test_hiring import scene, apply_body, change
from test_auth_isolation import create_job


def applied(scene):
    _, a, _, c, _, _, _, job, resume = scene
    row = c.post('/applications', json=apply_body(job, resume)).json()
    return row


def import_row(client, row):
    return client.post('/applications/' + row['id'] + '/resume-import', json={'expected_version': row['version']})


def test_import_download_and_analysis_use_application_snapshot_not_private_live_resume(scene):
    app, a, b, c, d, guest, users, job, resume = scene
    row = applied(scene)
    app.state.service.db.update('resumes', resume['id'], {'text': '私有修改不属于已授权的投递版本。'})
    listed = a.get('/resumes/applicants', params={'job_id': job['id']}).json()
    assert listed['total'] == 1 and listed['items'][0]['imported_resume_id'] is None
    assert 'resume_snapshot' not in listed['items'][0] and 'candidate_owner' not in listed['items'][0]
    path = '/applications/' + row['id'] + '/resume-download'
    downloaded = a.get(path)
    assert downloaded.status_code == 200 and downloaded.content.decode('utf-8-sig') == resume['text']
    assert "filename*=UTF-8''" in downloaded.headers['content-disposition']
    assert downloaded.headers['cache-control'] == 'no-store'
    response = import_row(a, row)
    assert response.status_code == 200, response.text
    imported = response.json()['resume']
    assert imported['id'] != resume['id'] and imported['text'] == resume['text']
    assert imported['owner'] == users[0]['actor'] and imported['source_application_id'] == row['id']
    assert imported['application_job_id'] == job['id'] and 'raw_file_path' not in imported
    assert a.get('/resumes/applicants').json()['items'][0]['imported_resume_id'] == imported['id']
    assert a.get('/resumes/' + imported['id'] + '/download').content.decode('utf-8-sig') == resume['text']
    assert len(a.post('/batches/run', json={'job_id': job['id']}).json()) == 1
    reports = a.post('/assessments', json={'job_id': job['id'], 'resume_ids': [imported['id']]}).json()
    assert len(reports['reports']) == 1 and not reports['errors']
    assert d.get('/resumes').json() == [] and len(c.get('/resumes').json()) == 1


def test_import_is_idempotent_even_with_concurrent_requests_and_reimport_after_delete(scene):
    app, a, _, _, _, _, users, _, _ = scene
    row = applied(scene)
    hiring = Hiring(app.state.service, app.state.auth)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: hiring.import_resume(row['id'], ApplicationResumeImport(expected_version=row['version']), users[0]['actor']), range(2)))
    assert len({r['resume']['id'] for r in results}) == 1
    assert sorted(r['already_imported'] for r in results) == [False, True]
    old_id = results[0]['resume']['id']
    assert a.delete('/resumes/' + old_id).status_code == 200
    assert a.get('/resumes/applicants').json()['items'][0]['imported_resume_id'] is None
    assert import_row(a, row).json()['resume']['id'] != old_id


def test_cross_enterprise_guest_candidate_and_forged_parameters_are_denied(scene):
    _, a, b, c, d, guest, _, job, resume = scene
    row = applied(scene)
    for client, expected in [(b, 404), (c, 403), (d, 403), (guest, 401)]:
        assert client.get('/applications/' + row['id'] + '/resume-download').status_code == expected
        assert import_row(client, row).status_code == expected
    assert b.get('/resumes/applicants').json()['total'] == 0
    assert b.get('/resumes/applicants', params={'job_id': job['id']}).status_code == 404
    assert a.post('/applications/' + row['id'] + '/resume-import', json={'expected_version': 1, 'text': '伪造内容', 'owner': 'enterprise:other'}).status_code == 422
    assert a.post('/applications/' + row['id'] + '/resume-import', json={'expected_version': 1}, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    assert a.get('/resumes/' + resume['id'] + '/download').status_code == 404


def test_imported_materials_and_reports_disappear_after_withdrawal(scene):
    app, a, _, c, _, _, users, job, resume = scene
    row = applied(scene)
    imported = import_row(a, row).json()['resume']
    a.post('/batches/run', json={'job_id': job['id']})
    report = a.post('/assessments', json={'job_id': job['id'], 'resume_ids': [imported['id']]}).json()['reports'][0]
    assert a.post('/reviews', json={'report_id': report['id'], 'action': '确认', 'reason': '对照授权材料完成核对'}).status_code == 200
    event = app.state.service.db.list('review_events', owner=users[0]['actor'], report_id=report['id'])[0]
    memory = app.state.service.db.insert('calibration_memory', {'pattern': '授权材料关联的合成校准记录', 'confirmed': True}, users[0]['actor'], 'synthetic', job_id=job['id'], source_event_id=event['id'])
    assert a.get('/memory').json()[0]['id'] == memory['id']
    assert change(c, row, 'withdraw').status_code == 200
    assert a.get('/resumes').json() == [] and a.get('/resumes/applicants').json()['total'] == 0
    for path in ['/applications/' + row['id'] + '/resume-download', '/resumes/' + imported['id'] + '/download', '/assessments/' + report['id']]:
        assert a.get(path).status_code == 403
    assert import_row(a, row).status_code == 403
    assert a.get('/batches', params={'job_id': job['id']}).json() == []
    assert a.get('/assessments').json() == []
    assert a.get('/memory').json() == []
    assert a.get('/candidates/ranking', params={'job_id': job['id']}).json() == []
    assert report['display_name'] not in a.get('/candidates/export', params={'job_id': job['id']}).text
    assert a.post('/assessments', json={'job_id': job['id'], 'resume_ids': [imported['id']]}).status_code == 403
    assert c.get('/resumes/' + resume['id'] + '/download').status_code == 200


def test_original_job_scope_is_enforced_and_stale_import_is_rejected(scene):
    _, a, _, _, _, _, _, job, _ = scene
    row = applied(scene)
    assert import_row(a, {**row, 'version': 999}).status_code == 409
    imported = import_row(a, row).json()['resume']
    another_job = create_job(a)
    assert a.post('/assessments', json={'job_id': another_job['id'], 'resume_ids': [imported['id']]}).json()['detail']['code'] == 'RESUME_JOB_SCOPE'
    assert a.post('/batches/run', json={'job_id': another_job['id']}).json() == []
    assert a.get('/resumes/applicants', params={'job_id': another_job['id']}).json()['total'] == 0
    assert a.get('/resumes/applicants', params={'q': '不存在的求职者'}).json()['total'] == 0


def test_consent_rechecked_after_model_finishes_and_company_suspension_blocks_import(scene, monkeypatch):
    app, a, _, c, _, _, _, job, _ = scene
    row = applied(scene)
    imported = import_row(a, row).json()['resume']
    original = app.state.service.evaluate
    def evaluate(*args):
        result = original(*args)
        assert change(c, row, 'withdraw').status_code == 200
        return result
    monkeypatch.setattr(app.state.service, 'evaluate', evaluate)
    result = a.post('/assessments', json={'job_id': job['id'], 'resume_ids': [imported['id']]}).json()
    assert not result['reports'] and result['errors'][0]['code'] == 'RESUME_CONSENT_UNAVAILABLE'
    assert app.state.service.db.list('ability_reports') == []
    monkeypatch.setattr(app.state.service, 'evaluate', original)
    second = applied(scene)
    app.state.service.db.update('job_profiles', job['id'], {'moderation_status': 'suspended'})
    assert import_row(a, second).status_code == 403
    assert a.get('/applications/' + second['id'] + '/resume-download').status_code == 403
