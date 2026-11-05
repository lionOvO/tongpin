"""Manual material edits use synthetic accounts and never invoke a model."""
import time
from uuid import uuid4
import pytest
from test_ai_workspace import setup, TEXT, PATH, mock_provider, turn
from app.deterministic import parse_jd


def payload(session, kind='resume', **overrides):
    return {'kind': kind, 'title': '修改后的合成简历' if kind == 'resume' else '个人后端参照',
        'text': TEXT + '\n项目补充：本人负责归还接口的异常处理与测试。',
        'expected_version': session['version'], 'request_id': str(uuid4()), **overrides}


def edit(client, session, body):
    return client.post(f"{PATH}/{session['id']}/materials/edit", json=body)


def test_resume_edit_preserves_history_notes_model_and_original(setup, monkeypatch):
    app, first, _, user, _, resume, session = setup
    calls = mock_provider(app, monkeypatch)
    session = turn(first, session).json()
    session = first.post(f"{PATH}/{session['id']}/additions", json={'text': '本人负责测试，具体是验证借阅与归还的正常及异常流程。', 'expected_version': session['version']}).json()
    old = first.get(f"{PATH}/{session['id']}").json()
    result = edit(first, session, payload(session))
    assert result.status_code == 200, result.text
    new = result.json()
    assert new['id'] != old['id'] and new['resume_id'] != resume['id']
    assert new['notes'] == old['notes'] and new['messages'] == []
    assert new['analysis'] is None and new['drafts'] == []
    assert new['model_id'] == old['model_id']
    assert new['resume']['revision_kind'] == 'user_edited_material'
    assert any('本人修改' in source['label'] for source in new['sources'])
    history = first.get(f"{PATH}/{old['id']}").json()
    assert history['messages'] == old['messages'] and history['resume']['text'] == TEXT
    stored = app.state.service.db.get('resumes', new['resume_id'])
    assert stored['parent_resume_id'] == resume['id'] and stored['owner'] == user['actor']
    assert 'raw_file_path' not in stored and 'source_hash' not in stored
    assert len(calls) == 1  # Saving manual text makes no model request.


def test_edit_public_enterprise_job_creates_only_private_candidate_copy(setup):
    app, first, _, user, _, resume, _ = setup
    svc = app.state.service
    jd = '岗位职责：Python 开发后端接口及接口测试。任职要求：掌握 Python 与 SQL。'
    public = svc.db.insert('job_profiles', {'title': '企业真实岗位合成例', 'source_jd': jd, 'profile': parse_jd(jd),
        'version': 1, 'status': '已确认', 'published': True, 'history': []}, 'enterprise:synthetic')
    svc.enterprise_owner_verified = lambda actor: actor == 'enterprise:synthetic'
    session = first.post(PATH, json={'resume_id': resume['id'], 'job_id': public['id']}).json()
    result = edit(first, session, payload(session, 'job', text=jd + '\n个人参照补充：了解接口性能测试。'))
    assert result.status_code == 200, result.text
    new = result.json()
    assert new['resume_id'] == resume['id'] and new['job_id'] != public['id']
    private = svc.db.get('job_profiles', new['job_id'])
    assert private['owner'] == user['actor'] and not private['published']
    assert private['source_type'] == 'user_paste' and private['parent_job_id'] == public['id']
    assert new['job']['personal_reference'] is True
    assert svc.db.get('job_profiles', public['id']) == public


def test_material_edit_denies_other_owner_unknown_fields_and_missing_job(setup):
    app, first, second, _, _, _, session = setup
    assert edit(second, session, payload(session)).status_code == 404
    assert edit(first, session, payload(session, owner='enterprise:fake', published=True)).status_code == 422
    assert edit(first, session, payload(session, 'job')).json()['detail']['code'] == 'AI_JOB_EMPTY'
    assert len(app.state.service.db.list('resumes')) == 1


def test_material_edit_retry_is_idempotent_but_payload_reuse_is_rejected(setup):
    app, first, _, _, _, _, session = setup
    body = payload(session)
    created = edit(first, session, body).json()
    assert edit(first, session, body).json()['id'] == created['id']
    assert edit(first, session, {**body, 'text': body['text'] + '\n新增内容'}).status_code == 409
    assert len(app.state.service.db.list('resumes')) == 2
    assert len(first.get(PATH).json()) == 1  # Unchosen material staging is not a conversation.


@pytest.mark.parametrize('busy', [False, True])
def test_material_edit_conflict_and_processing_never_write_new_material(setup, busy):
    app, first, _, _, _, _, session = setup
    if busy:
        app.state.service.db.update('ai_sessions', session['id'], {'running': 'synthetic', 'running_until': time.time() + 60})
        body = payload(session)
    else:
        body = payload(session, expected_version=99)
    result = edit(first, session, body)
    assert result.status_code == 409
    assert result.json()['detail']['code'] == ('AI_BUSY' if busy else 'AI_VERSION_CONFLICT')
    assert len(app.state.service.db.list('resumes')) == 1


def test_material_edit_validation_and_unchanged_material(setup):
    app, first, _, _, _, resume, session = setup
    assert edit(first, session, payload(session, title=' ')).status_code == 422
    assert edit(first, session, payload(session, title='x' * 41)).status_code == 422
    assert edit(first, session, payload(session, text=' ' * 22)).status_code == 422
    assert edit(first, session, payload(session, request_id='bad-id')).status_code == 422
    assert edit(first, session, payload(session, title=resume['display_name'], text=TEXT)).json()['detail']['code'] == 'AI_MATERIAL_UNCHANGED'
    assert len(app.state.service.db.list('resumes')) == 1


def test_material_edit_preserves_existing_self_reported_provenance(setup):
    app, first, _, _, _, resume, session = setup
    reported = TEXT.splitlines()[-1]
    app.state.service.db.update('resumes', resume['id'], {'revision_kind': 'user_confirmed_ai_draft', 'self_reported_paragraphs': [reported], 'supplement_notice': True})
    new = edit(first, session, payload(session)).json()
    stored = app.state.service.db.get('resumes', new['resume_id'])
    assert reported in stored['self_reported_paragraphs']
    assert '本人修改' in next(s for s in new['sources'] if s['text'] == reported)['label']


def test_material_edit_rolls_back_when_new_session_fails(setup, monkeypatch):
    app, first, _, _, _, _, session = setup
    db = app.state.service.db
    original_insert = db.insert
    def fail(table, *args, **kwargs):
        if table == 'ai_sessions':
            raise RuntimeError('synthetic persistence failure')
        return original_insert(table, *args, **kwargs)
    monkeypatch.setattr(db, 'insert', fail)
    with pytest.raises(RuntimeError):
        edit(first, session, payload(session))
    assert len(db.list('resumes')) == 1
    assert db.get('ai_sessions', session['id'])['version'] == 1
