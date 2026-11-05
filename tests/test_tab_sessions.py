"""One real cookie jar, several independently selected tab sessions."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_session_scopes import browser, PASSWORD, USER_PHONE, STAFF_PHONE


def login(client, phone=USER_PHONE, scope='user', tab=None):
    headers = {'X-Session-Tab': tab or str(uuid4()), 'X-Session-Scope': scope}
    path = '/auth/admin/login/password' if scope == 'admin' else '/auth/login/password'
    response = client.post(path, json={'phone': phone, 'password': PASSWORD}, headers=headers)
    assert response.status_code == 200, response.text
    headers['X-CSRF-Token'] = response.json()['csrf_token']
    return headers, response.json(), response


def test_same_browser_logins_refresh_download_and_logout_are_independent(browser):
    client, legacy, resume, staff = browser
    a, alice, _ = login(client)
    b, bob, _ = login(client, STAFF_PHONE)
    assert alice['user']['id'] != bob['user']['id']
    for _ in range(2):
        assert client.get('/auth/me', headers=a).json() == alice
        assert client.get('/auth/me', headers=b).json() == bob
        assert client.get('/resumes', headers=a).json()[0]['id'] == resume['id']
        assert client.get('/resumes', headers=b).json() == []
        assert client.get(f"/resumes/{resume['id']}/download", headers=a).status_code == 200
        assert client.get(f"/resumes/{resume['id']}/download", headers=b).status_code == 404
    assert client.post('/auth/logout', headers=b).status_code == 200
    assert client.get('/auth/me', headers=b).status_code == 401
    assert client.get('/auth/me', headers=a).json() == alice
    assert client.get('/auth/me').json()['user'] == legacy
    assert client.get('/auth/admin/me').json() == staff


def test_new_tab_never_falls_back_to_the_latest_shared_cookie(browser):
    client, *_ = browser
    a, _, _ = login(client)
    unknown = {'X-Session-Tab': str(uuid4())}
    assert client.get('/auth/me', headers=unknown).status_code == 401
    assert client.get('/resumes', headers=unknown).status_code == 401
    # Knowing a selector without its HttpOnly credential does not authenticate.
    with TestClient(client.app) as guest:
        assert guest.get('/auth/me', headers=a).status_code == 401


def test_csrf_scope_and_cookie_security_are_preserved(browser):
    client, *_ = browser
    a, _, response = login(client)
    b, _, _ = login(client, STAFF_PHONE)
    admin, staff, _ = login(client, STAFF_PHONE, scope='admin')
    cookie = response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie and 'max-age=43200' in cookie
    assert client.post('/auth/logout', headers={**a, 'X-CSRF-Token': b['X-CSRF-Token']}).status_code == 403
    assert client.post('/auth/logout', headers={**a, 'Origin': 'https://foreign.example'}).status_code == 403
    assert client.get('/auth/admin/me', headers=a).status_code == 401
    assert client.get('/admin/overview', headers=b).status_code == 401
    assert client.get('/auth/admin/me', headers=admin).json() == staff
    assert client.post('/auth/logout', headers=b).status_code == 200
    assert client.get('/auth/admin/me', headers=admin).status_code == 200


def test_workspace_fork_preserves_source_tab_and_uses_new_csrf(browser):
    client, *_ = browser
    a, recruiter, _ = login(client, STAFF_PHONE)
    target = str(uuid4())
    response = client.post('/auth/workspace', json={'role': 'candidate'}, headers={**a, 'X-New-Session-Tab': target})
    assert response.status_code == 200, response.text
    b = {**a, 'X-Session-Tab': target, 'X-CSRF-Token': response.json()['csrf_token']}
    assert client.get('/auth/me', headers=a).json() == recruiter
    assert client.get('/auth/me', headers=b).json()['user']['role'] == 'candidate'
    assert client.post('/auth/logout', headers={**b, 'X-CSRF-Token': a['X-CSRF-Token']}).status_code == 403
    assert client.post('/auth/logout', headers=b).status_code == 200
    assert client.get('/auth/me', headers=a).json() == recruiter


@pytest.mark.parametrize('value', ['', '../other', 'x' * 200, 'not-a-uuid', 'a' * 32])
def test_malformed_selector_is_rejected_without_using_legacy_session(browser, value):
    client, legacy, *_ = browser
    assert client.get('/auth/me', headers={'X-Session-Tab': value}).status_code == 400
    assert client.get('/auth/me').json()['user'] == legacy


def test_password_reset_revokes_only_that_accounts_all_tabs(browser):
    client, *_ = browser
    a, _, _ = login(client)
    a2, _, _ = login(client)
    b, bob, _ = login(client, STAFF_PHONE)
    auth = client.app.state.auth
    with auth.tx() as cx:
        cx.execute('DELETE FROM limits')
    assert client.post('/auth/sms/send', json={'phone': USER_PHONE, 'purpose': 'reset'}, headers=a).status_code == 200
    response = client.post('/auth/password/reset', json={'phone': USER_PHONE, 'code': auth.sms.codes[USER_PHONE], 'password': 'New-password-2026'}, headers=a)
    assert response.status_code == 200, response.text
    assert client.get('/auth/me', headers=a2).status_code == 401
    assert client.get('/auth/me', headers=a).status_code == 200
    assert client.get('/auth/me', headers=b).json() == bob
