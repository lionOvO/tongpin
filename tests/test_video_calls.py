"""Real auth and synthetic applications; no camera, media, SMS or AI network."""
import time
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from test_hiring import scene, apply_body, change
from test_message_center import accepted


def start(client, row, tab=None, request=None):
    tab = tab or str(uuid4())
    return client.post('/video-calls', json={'application_id': row['id'], 'client_id': tab,
        'request_id': request or str(uuid4())}), tab


def act(client, call, tab, action):
    return client.post(f"/video-calls/{call['id']}/actions", json={'client_id': tab, 'action': action})


def sync(client, call, tab, after=0):
    return client.post(f"/video-calls/{call['id']}/sync", json={'client_id': tab, 'after': after})


def signal(client, call, tab, kind='offer', **extras):
    body = {'client_id': tab, 'request_id': str(uuid4()), 'kind': kind}
    body.update({'candidate': {'candidate': 'candidate:1 1 udp 1 127.0.0.1 1234 typ host'}} if kind == 'ice' else {'sdp': 'v=0\r\ns=synthetic\r\n'})
    return client.post(f"/video-calls/{call['id']}/signals", json={**body, **extras})


def test_invite_answer_signal_hangup_and_private_history(scene):
    app, a, _, c, _, _, _, _, _ = scene
    row = accepted(scene)
    response, caller_tab = start(a, row); assert response.status_code == 200, response.text
    call = response.json(); receiver_tab = str(uuid4())
    assert call['status'] == 'ringing' and call['direction'] == 'outgoing'
    incoming = c.get('/video-calls/active', params={'client_id': receiver_tab}).json()
    assert incoming[0]['direction'] == 'incoming' and incoming[0]['can_control']
    assert signal(a, call, caller_tab).status_code == 409  # Nothing before consent.
    assert act(a, call, caller_tab, 'accept').status_code == 403
    assert act(c, call, receiver_tab, 'accept').json()['status'] == 'accepted'
    assert signal(a, call, caller_tab).json()['seq'] == 1
    assert signal(c, call, receiver_tab, 'answer').json()['seq'] == 2
    assert signal(a, call, caller_tab, 'ice').json()['seq'] == 3
    got = sync(c, call, receiver_tab).json()
    assert [s['seq'] for s in got['signals']] == [1, 3]
    assert sync(c, call, receiver_tab, after=3).json()['signals'] == []
    assert [s['seq'] for s in sync(a, call, caller_tab).json()['signals']] == [2]
    assert act(a, call, caller_tab, 'connected').json()['connected_at']
    assert act(c, call, receiver_tab, 'end').json()['reason'] == 'ended'
    ended = sync(a, call, caller_tab).json()
    assert ended['call']['status'] == 'ended' and ended['signals'] == []
    stored = app.state.service.db.get('video_calls', call['id'])
    assert stored['signals'] == [] and stored['leases'] == {}
    assert c.get('/video-calls/active', params={'client_id': receiver_tab}).json() == []
    history = a.get('/video-calls', params={'application_id': row['id']}).json()
    assert history[0]['ended_at'] and 'sdp' not in str(history) and 'caller' not in history[0]
    # Call signaling does not race with the existing message optimistic version.
    assert a.get('/applications/' + row['id']).json()['version'] == row['version']


def test_only_accepted_owned_available_conversations_and_valid_user_session(scene):
    app, a, b, c, d, guest, users, job, resume = scene
    row = c.post('/applications', json=apply_body(job, resume)).json()
    assert start(c, row)[0].status_code == 409
    row = change(a, row, 'invite', '邀请了解岗位。').json()
    assert start(c, row)[0].status_code == 409
    row = change(c, row, 'accept').json()
    response, tab = start(a, row); call = response.json()
    for outsider in (b, d):
        assert start(outsider, row)[0].status_code == 404
        assert outsider.get('/video-calls', params={'application_id': row['id']}).status_code == 404
        assert sync(outsider, call, tab).status_code == 404
        assert act(outsider, call, tab, 'end').status_code == 404
        assert signal(outsider, call, tab).status_code == 404
    assert start(guest, row)[0].status_code == 401
    assert c.get('/video-calls/active', params={'client_id': str(uuid4())}, headers={'X-Session-Scope': 'admin'}).status_code == 403
    assert a.post(f"/video-calls/{call['id']}/actions", json={'client_id': tab, 'action': 'end'}, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    changed = change(c, row, 'withdraw').json()
    assert changed['status'] == 'withdrawn'
    result = sync(a, call, tab).json()['call']
    assert result['status'] == 'ended' and result['reason'] == 'unavailable'
    assert start(c, changed)[0].status_code == 409


def test_multi_tab_answer_claim_and_signals_are_isolated(scene):
    _, a, _, c, _, _, _, _, _ = scene
    row = accepted(scene); response, tab = start(a, row); call = response.json()
    receiver, other = str(uuid4()), str(uuid4())
    assert act(c, call, receiver, 'accept').status_code == 200
    assert act(c, call, other, 'accept').status_code == 409
    assert signal(a, call, tab).status_code == 200
    assert sync(c, call, other).json()['signals'] == []
    assert not sync(c, call, other).json()['call']['can_control']
    assert act(c, call, other, 'end').status_code == 409
    assert signal(c, call, other, 'answer').status_code == 409
    assert signal(a, call, tab, 'answer').status_code == 403
    assert signal(c, call, receiver, 'offer').status_code == 403


def test_atomic_busy_race_and_request_retry(scene):
    _, a, _, c, _, _, _, _, _ = scene
    row = accepted(scene)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda client: start(client, row)[0].status_code, (a, c)))
    assert sorted(results) == [200, 409]


def test_idempotent_create_and_signal_with_bounded_validated_payload(scene):
    _, a, _, c, _, _, _, _, _ = scene
    row = accepted(scene); request, tab = str(uuid4()), str(uuid4())
    response, _ = start(a, row, tab, request); call = response.json()
    assert start(a, row, tab, request)[0].json()['id'] == call['id']
    assert start(a, row)[0].status_code == 409
    receiver = str(uuid4()); act(c, call, receiver, 'accept')
    signal_id = str(uuid4())
    first = signal(a, call, tab, request_id=signal_id).json()
    assert signal(a, call, tab, request_id=signal_id).json() == first
    assert signal(a, call, tab, request_id=signal_id, sdp='different').status_code == 409
    assert signal(a, call, tab, sdp='x' * 64001).status_code == 422
    assert signal(a, call, tab, sender='forged').status_code == 422
    assert signal(a, call, tab, kind='ice', candidate={'candidate': 'x', 'unknown': 'x'}).status_code == 422
    for _ in range(239):
        assert signal(a, call, tab, 'ice').status_code == 200
    assert signal(a, call, tab, 'ice').status_code == 409


def test_missed_and_disconnected_calls_expire_and_clear_signals(scene):
    app, a, _, c, _, _, _, _, _ = scene
    row = accepted(scene); response, tab = start(a, row); call = response.json()
    app.state.service.db.update('video_calls', call['id'], {'created_ts': time.time() - 46})
    assert sync(a, call, tab).json()['call']['reason'] == 'missed'
    response, tab = start(c, row); call = response.json(); receiver = str(uuid4())
    act(a, call, receiver, 'accept'); signal(c, call, tab)
    stored = app.state.service.db.get('video_calls', call['id'])
    app.state.service.db.update('video_calls', call['id'], {'leases': {**stored['leases'], stored['caller']: time.time() - 41}})
    assert signal(c, call, tab, 'ice').status_code == 409
    assert app.state.service.db.get('video_calls', call['id'])['status'] == 'ended'
    assert app.state.service.db.get('video_calls', call['id'])['signals'] == []
    assert sync(a, call, receiver).json()['call']['reason'] == 'disconnected'
    assert app.state.service.db.get('video_calls', call['id'])['signals'] == []


def test_decline_cancel_and_disabled_counterpart(scene):
    app, a, _, c, _, _, users, job, _ = scene
    row = accepted(scene); response, tab = start(a, row); call = response.json()
    assert act(c, call, str(uuid4()), 'decline').json()['reason'] == 'declined'
    assert act(a, call, tab, 'end').json()['reason'] == 'declined'
    response, tab = start(c, row); call = response.json()
    assert act(c, call, tab, 'end').json()['reason'] == 'cancelled'
    response, tab = start(a, row); call = response.json()
    app.state.service.db.update('job_profiles', job['id'], {'moderation_status': 'suspended'})
    assert sync(c, call, str(uuid4())).json()['call']['reason'] == 'unavailable'
