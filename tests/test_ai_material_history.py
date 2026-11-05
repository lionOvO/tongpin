"""Explicit material decisions and private conversation history; synthetic data only."""
import pytest
from test_ai_workspace import setup, TEXT, PATH, mock_provider, turn
from test_ai_material_edit import payload, edit


def fresh(client, row):
    return client.get(f"{PATH}/{row['id']}").json()


def decide(client, row, choice='update', **overrides):
    return client.post(f"{PATH}/{row['id']}/materials/resolve", json={
        'choice': choice, 'pending_session_id': row['pending_materials']['session_id'],
        'expected_version': row['version'], **overrides})


def test_save_stays_on_old_materials_with_persistent_notice_and_no_phantom_history(setup, monkeypatch):
    app, first, second, _, _, _, row = setup
    calls = mock_provider(app, monkeypatch)
    row = turn(first, row).json()
    edited = edit(first, row, payload(row)).json()
    pending = fresh(first, row)
    assert pending['id'] == row['id'] and pending['resume_id'] == row['resume_id']
    assert pending['messages'] == row['messages'] and pending['analysis'] == row['analysis']
    assert pending['pending_materials']['session_id'] == edited['id']
    assert pending['pending_materials']['resume']['text'] != TEXT
    assert fresh(first, row)['pending_materials'] == pending['pending_materials']
    assert [r['id'] for r in first.get(PATH).json()] == [row['id']]
    assert second.get(PATH).json() == []
    assert turn(first, pending).json()['detail']['code'] == 'AI_MATERIAL_PENDING'
    assert turn(first, edited).json()['detail']['code'] == 'AI_MATERIAL_PENDING'
    assert len(calls) == 1


def test_consecutive_resume_and_job_edits_combine_then_branch_without_touching_old_chat(setup, monkeypatch):
    app, first, _, _, _, resume, _ = setup
    calls = mock_provider(app, monkeypatch)
    row = first.post(PATH, json={'resume_id': resume['id'], 'title': '合成后端岗位',
        'jd': '岗位职责：使用 Python 开发后端接口，维护数据查询并编写自动化测试。'}).json()
    row = turn(first, row).json()
    new_resume = edit(first, row, payload(row)).json()['resume_id']
    pending = fresh(first, row)
    changed = edit(first, pending, payload(pending, 'job')).json()
    pending = fresh(first, row)
    assert pending['pending_materials']['resume']['id'] == new_resume
    new = decide(first, pending, 'new').json()
    assert new['id'] == changed['id'] and new['resume_id'] == new_resume
    assert new['job_id'] == changed['job_id'] and new['job']['personal_reference']
    assert new['messages'] == [] and new['analysis'] is None
    old = fresh(first, row)
    assert old['messages'] == row['messages'] and old['analysis'] == row['analysis']
    assert old['resume_id'] == resume['id'] and old['job_id'] == row['job_id']
    assert not old['pending_materials']
    history = first.get(PATH).json()
    assert {r['id'] for r in history} >= {row['id'], new['id']}
    assert next(r for r in history if r['id'] == row['id'])['message_count'] == 2
    assert decide(first, pending, 'new').json()['id'] == new['id']  # No duplicate branch.
    assert len(calls) == 1  # The user has not asked the new conversation to analyze yet.


def test_update_keeps_messages_resets_results_and_excludes_old_material_context(setup, monkeypatch):
    app, first, _, _, _, resume, row = setup
    calls = mock_provider(app, monkeypatch)
    row = turn(first, row, 'draft').json()
    app.state.service.db.update('ai_sessions', row['id'], {
        'agent_run': {'status': 'completed', 'label': '旧材料分析'},
        'agent_jobs': [], 'agent_comparison_id': 'old-comparison', 'agent_comparison_run': 'old-run'})
    original = row
    edit(first, row, payload(row))
    pending = fresh(first, row)
    result = decide(first, pending)
    assert result.status_code == 200, result.text
    updated = result.json()
    assert updated['id'] == row['id'] and updated['messages'] == original['messages']
    assert updated['resume_id'] != resume['id'] and updated['material_epoch'] == 1
    assert updated['analysis'] is None and updated['drafts'] == [] and not updated['pending_materials']
    assert updated['agent_run'] is None and updated['job_assistance']['comparison'] is None
    assert not app.state.service.db.get('ai_sessions', row['id'])['agent_comparison_id']
    assert app.state.service.db.get('ai_sessions', row['id'])['resume_id'] == updated['resume_id']
    archive = app.state.service.db.get('ai_sessions', row['id'])['material_archive'][-1]
    assert archive['analysis'] == original['analysis'] and archive['drafts'] == original['drafts']
    assert fresh(first, updated)['resume_id'] == updated['resume_id']
    assert decide(first, pending).json()['material_epoch'] == 1  # Retry does not clear new analysis.
    updated = turn(first, updated).json()
    assert calls[-1]['history'] == []
    assert any('归还接口' in s['text'] for s in calls[-1]['sources'])
    assert updated['analysis'] is not None and updated['messages'][-1]['material_epoch'] == 1
    updated = turn(first, updated, 'chat', '请继续检查修改后的职责描述。').json()
    assert len(calls[-1]['history']) == 2  # Original draft conversation never enters this context.
    assert all(m['material_epoch'] == 1 for m in updated['messages'][2:])
    assert updated['messages'][:2] == original['messages']


@pytest.mark.parametrize('choice', ['new', 'update'])
def test_decision_rejects_other_owner_stale_version_and_replaced_pending_revision(setup, choice):
    _, first, second, _, _, _, row = setup
    edit(first, row, payload(row))
    pending = fresh(first, row)
    assert decide(second, pending, choice).status_code == 404
    assert decide(first, pending, choice, expected_version=1).json()['detail']['code'] == 'AI_VERSION_CONFLICT'
    assert decide(first, pending, choice, owner='someone').status_code == 422
    edit(first, pending, payload(pending, title='再次修改后的简历'))
    latest = fresh(first, row)
    assert decide(first, latest, choice, pending_session_id=pending['pending_materials']['session_id']).json()['detail']['code'] == 'AI_MATERIAL_CHANGED'
    assert fresh(first, row)['resume_id'] == row['resume_id']


def test_failed_apply_rolls_back_sql_references_and_notice(setup, monkeypatch):
    app, first, _, _, _, _, row = setup
    edit(first, row, payload(row))
    pending = fresh(first, row)
    original_audit = app.state.service.db.audit
    def fail(event, *args, **kwargs):
        if event == 'AI 材料更新选择':
            raise RuntimeError('synthetic failure')
        return original_audit(event, *args, **kwargs)
    monkeypatch.setattr(app.state.service.db, 'audit', fail)
    with pytest.raises(RuntimeError):
        decide(first, pending)
    assert fresh(first, row)['resume_id'] == row['resume_id']
    assert fresh(first, row)['pending_materials'] == pending['pending_materials']


def test_unavailable_model_cannot_clear_old_analysis_and_new_dialogue_can_still_be_chosen(setup, monkeypatch):
    app, first, _, _, _, _, row = setup
    mock_provider(app, monkeypatch)
    row = turn(first, row).json()
    edit(first, row, payload(row))
    pending = fresh(first, row)
    app.state.service.settings.llm_mode = 'demo'
    assert decide(first, pending).status_code == 503
    assert fresh(first, row)['analysis'] == row['analysis']
    assert decide(first, pending, 'new').status_code == 200


def test_delete_old_dialogue_cleans_staging_without_deleting_saved_materials(setup):
    app, first, _, _, _, _, row = setup
    staged = edit(first, row, payload(row)).json()
    assert first.delete(f"{PATH}/{staged['id']}").status_code == 409
    assert first.delete(f"{PATH}/{row['id']}").status_code == 200
    assert app.state.service.db.get('ai_sessions', staged['id']) is None
    assert app.state.service.db.get('resumes', staged['resume_id']) is not None
    assert first.get(PATH).json() == []
