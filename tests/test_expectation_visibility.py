"""A saved visibility choice governs expectations in every related application."""
import pytest
from test_hiring import scene, apply_body, change
from test_auth_isolation import create_job, create_resume
from uuid import uuid4


def save(client, side, target, public, option=0):
    config = client.get('/config/preferences').json()
    result = client.post('/preferences/submit', json={
        'side': side, 'resume_id' if side == 'candidate' else 'job_id': target,
        'dimensions': {d['id']: d['options'][min(option, len(d['options']) - 1)] for d in config['dimensions']},
        'dimension_version': config['version'], 'share_with_counterparty': public})
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.parametrize('public,old_flag', [(True, None), (True, False), (False, True), (False, None)])
def test_new_application_uses_saved_visibility_instead_of_per_application_flag(scene, public, old_flag):
    app, enterprise, _, candidate, _, _, _, job, resume = scene
    saved = save(candidate, 'candidate', resume['id'], public)
    save(enterprise, 'enterprise', job['id'], True)
    body = apply_body(job, resume)
    if old_flag is None: body.pop('share_preferences')
    else: body['share_preferences'] = old_flag
    result = candidate.post('/applications', json=body)
    assert result.status_code == 200, result.text
    application = result.json()
    detail = enterprise.get('/applications/' + application['id']).json()
    assert bool(detail['candidate_preferences']) is public
    assert bool(detail['preference_comparison']) is public
    if public: assert detail['candidate_preferences']['id'] == saved['id']
    assert app.state.service.db.get('applications', application['id'])['consent']['preferences'] is public


def test_privacy_and_edits_apply_to_existing_applications_without_sync_or_resubmission(scene):
    _, enterprise, _, candidate, _, _, _, job, resume = scene
    save(enterprise, 'enterprise', job['id'], True)
    saved = save(candidate, 'candidate', resume['id'], True)
    application = candidate.post('/applications', json=apply_body(job, resume)).json()
    another_job = create_job(enterprise)
    enterprise.put('/jobs/' + another_job['id'] + '/visibility', json={'published': True})
    save(enterprise, 'enterprise', another_job['id'], True)
    second = candidate.post('/applications', json=apply_body(another_job, resume)).json()
    other_resume = create_resume(candidate)
    other_saved = save(candidate, 'candidate', other_resume['id'], True)
    updated = save(candidate, 'candidate', resume['id'], True, option=1)
    assert updated['id'] != saved['id']
    for row in (application, second):
        current = enterprise.get('/applications/' + row['id']).json()
        assert current['candidate_preferences']['id'] == updated['id']
        assert current['resume_snapshot']['text'] == resume['text']
        assert current['version'] == row['version']  # No stale invitation/chat versions.
    private = save(candidate, 'candidate', resume['id'], False)
    for row in (application, second):
        current = enterprise.get('/applications/' + row['id']).json()
        assert current['candidate_preferences'] is None and current['preference_comparison'] is None
        assert current['resume_shared'] is True
    own = candidate.get('/preferences').json()
    assert next(r for r in own if r['id'] == private['id'])['share_with_counterparty'] is False
    assert next(r for r in own if r['id'] == other_saved['id'])['share_with_counterparty'] is True
    republished = save(candidate, 'candidate', resume['id'], True)
    assert enterprise.get('/applications/' + application['id']).json()['candidate_preferences']['id'] == republished['id']


def test_private_team_expectations_can_be_saved_and_hidden_from_candidates(scene):
    _, enterprise, _, candidate, _, _, _, job, resume = scene
    save(candidate, 'candidate', resume['id'], True)
    save(enterprise, 'enterprise', job['id'], True)
    application = candidate.post('/applications', json=apply_body(job, resume)).json()
    save(enterprise, 'enterprise', job['id'], False)
    detail = candidate.get('/applications/' + application['id']).json()
    assert detail['enterprise_preferences'] is None and detail['preference_comparison'] is None
    assert detail['candidate_preferences'] is not None


def test_private_setting_blocks_current_and_historical_comparisons_and_participant_listing(scene):
    _, enterprise, outsider, candidate, _, guest, _, job, resume = scene
    save(candidate, 'candidate', resume['id'], True)
    save(enterprise, 'enterprise', job['id'], True)
    application = candidate.post('/applications', json=apply_body(job, resume)).json()
    body = {'job_id': job['id'], 'resume_id': resume['id']}
    result = enterprise.post('/matches/run', json=body)
    assert result.status_code == 200, result.text
    match = result.json()
    updated = save(candidate, 'candidate', resume['id'], True, option=1)
    assert enterprise.post('/matches/run', json=body).json()['cand_submission_id'] == updated['id']
    assert candidate.post('/matches/run', json=body).status_code == 200
    save(candidate, 'candidate', resume['id'], False)
    for client in (enterprise, candidate):
        assert client.get('/matches').json() == []
        assert client.get('/matches/' + match['id']).status_code == 404
        assert client.post('/matches/run', json={**body, 'share_with_job': True}).status_code == 403
    assert enterprise.get('/matches/participants', params={'job_id': job['id']}).json() == []
    assert outsider.get('/applications/' + application['id']).status_code == 404
    assert guest.get('/preferences').status_code == 401


def test_public_expectations_do_not_restore_withdrawn_application_access(scene):
    _, enterprise, _, candidate, _, _, _, job, resume = scene
    save(candidate, 'candidate', resume['id'], True)
    application = candidate.post('/applications', json=apply_body(job, resume)).json()
    change(candidate, application, 'withdraw')
    save(candidate, 'candidate', resume['id'], True, option=1)
    detail = enterprise.get('/applications/' + application['id']).json()
    assert detail['candidate_preferences'] is None and detail['resume_snapshot'] is None
    assert enterprise.post('/matches/run', json={'job_id': job['id'], 'resume_id': resume['id']}).status_code == 404


@pytest.mark.parametrize('private_side', ['candidate', 'enterprise', 'both'])
def test_private_expectations_do_not_block_invitation_acceptance_or_chat(scene, private_side):
    _, enterprise, outsider, candidate, other_candidate, guest, _, job, resume = scene
    save(candidate, 'candidate', resume['id'], True)
    save(enterprise, 'enterprise', job['id'], True)
    application = candidate.post('/applications', json=apply_body(job, resume)).json()
    if private_side in ('candidate', 'both'): save(candidate, 'candidate', resume['id'], False)
    if private_side in ('enterprise', 'both'): save(enterprise, 'enterprise', job['id'], False)
    # A visibility change must not invalidate in-flight invitation versions.
    invitation = change(enterprise, application, 'invite', '希望进一步了解你负责的项目。')
    assert invitation.status_code == 200, invitation.text
    accepted = change(candidate, invitation.json(), 'accept')
    assert accepted.status_code == 200, accepted.text
    row = accepted.json()
    for client, text in ((enterprise, '可以介绍项目中的职责吗？'), (candidate, '我负责接口开发和异常流程测试。')):
        response = client.post('/applications/' + row['id'] + '/messages', json={
            'text': text, 'expected_version': row['version'], 'request_id': str(uuid4())})
        assert response.status_code == 200, response.text
        row = response.json()
    for client in (enterprise, candidate):
        detail = client.get('/applications/' + row['id']).json()
        assert detail['status'] == 'accepted' and detail['resume_snapshot']
        assert len(detail['messages']) == 2
        assert bool(detail['candidate_preferences']) is (private_side == 'enterprise')
        assert bool(detail['enterprise_preferences']) is (private_side == 'candidate')
        assert detail['preference_comparison'] is None
    for client in (outsider, other_candidate):
        assert client.get('/applications/' + row['id']).status_code == 404
    assert guest.get('/applications/' + row['id']).status_code == 401
