"""Browser cookie jars may hold user and staff sessions without crossing boundaries."""
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from app.auth import ADMIN_COOKIE, COOKIE, Auth, digest
from app.main import create_app
from app.settings import Settings
from auth_helpers import FakeSMS, sign_in
from scripts.manage_accounts import promote
from test_auth_isolation import create_resume

PASSWORD = 'Scenario-password-2026'
USER_PHONE = '13800000581'
STAFF_PHONE = '13800000582'


@pytest.fixture
def browser(tmp_path):
    settings = Settings(data_dir=tmp_path, env='demo', auto_seed=False)
    settings.llm_mode = 'demo'; settings.vector = False
    app = create_app(settings); app.state.auth.sms = FakeSMS()
    with TestClient(app) as setup, TestClient(app) as client:
        sign_in(setup, STAFF_PHONE)
        promote(app.state.auth, STAFF_PHONE)
        user = sign_in(client, USER_PHONE)
        resume = create_resume(client)
        result = client.post('/auth/admin/login/password', json={'phone': STAFF_PHONE, 'password': PASSWORD})
        assert result.status_code == 200, result.text
        yield client, user, resume, result.json()


def test_same_browser_keeps_both_identities_and_private_owners(browser):
    client, user, resume, staff = browser
    assert client.cookies.get(COOKIE) and client.cookies.get(ADMIN_COOKIE)
    assert client.get('/auth/me').json()['user'] == user
    assert client.get('/auth/admin/me').json()['user'] == staff['user']
    assert client.get('/resumes').json()[0]['id'] == resume['id']
    assert client.get('/resumes', headers={'X-Session-Scope': 'admin'}).json() == []
    assert client.get('/admin/overview').status_code == 200
    assert client.get('/config/packs').status_code == 403
    assert client.get('/config/packs', headers={'X-Session-Scope': 'admin'}).status_code == 200


@pytest.mark.parametrize('scope', ['user', 'admin'])
def test_logout_only_revokes_selected_cookie_and_session(browser, scope):
    client, user, resume, staff = browser
    other_cookie = client.cookies.get(ADMIN_COOKIE if scope == 'user' else COOKIE)
    csrf = client.get('/auth/me').json()['csrf_token'] if scope == 'user' else staff['csrf_token']
    path = '/auth/logout' if scope == 'user' else '/auth/admin/logout'
    result = client.post(path, headers={'X-Session-Scope': scope, 'X-CSRF-Token': csrf})
    assert result.status_code == 200
    assert client.cookies.get(ADMIN_COOKIE if scope == 'user' else COOKIE) == other_cookie
    assert client.get('/auth/me' if scope == 'user' else '/auth/admin/me').status_code == 401
    assert client.get('/auth/admin/me' if scope == 'user' else '/auth/me').status_code == 200


def test_user_relogin_and_failed_staff_login_do_not_rotate_staff_session(browser):
    client, user, resume, staff = browser
    admin_cookie = client.cookies.get(ADMIN_COOKIE)
    result = client.post('/auth/login/password', json={'phone': USER_PHONE, 'password': PASSWORD, 'role': 'candidate'})
    assert result.status_code == 200 and result.json()['user'] == user
    failed = client.post('/auth/admin/login/password', json={'phone': USER_PHONE, 'password': PASSWORD})
    assert failed.status_code == 403 and not failed.headers.get('set-cookie')
    assert client.cookies.get(ADMIN_COOKIE) == admin_cookie
    assert client.get('/auth/admin/me').json() == staff
    assert client.get('/resumes').json()[0]['id'] == resume['id']


def test_scope_headers_and_swapped_cookies_cannot_promote_user_tokens(browser):
    client, user, resume, staff = browser
    user_cookie = client.cookies.get(COOKIE); admin_cookie = client.cookies.get(ADMIN_COOKIE)
    with TestClient(client.app) as forged:
        forged.cookies.set(ADMIN_COOKIE, user_cookie)
        assert forged.get('/auth/admin/me').status_code == 401
        assert forged.get('/admin/overview', headers={'X-Session-Scope':'user', 'X-Role':'admin'}).status_code == 401
        assert forged.get('/config/packs', headers={'X-Session-Scope':'admin'}).status_code == 401
        forged.cookies.clear(); forged.cookies.set(COOKIE, admin_cookie)
        assert forged.get('/auth/me').status_code == 401
        assert forged.get('/admin/overview').status_code == 401
        forged.cookies.clear(); forged.cookies.set(COOKIE, user_cookie)
        assert forged.get('/auth/admin/me').status_code == 401  # No fallback to ordinary cookie.


def test_csrf_is_bound_to_selected_session_and_staff_cannot_switch_workspace(browser):
    client, user, resume, staff = browser
    user_csrf = client.get('/auth/me').json()['csrf_token']
    assert client.post('/auth/admin/logout', headers={'X-CSRF-Token':user_csrf}).status_code == 403
    assert client.post('/auth/logout', headers={'X-CSRF-Token':staff['csrf_token']}).status_code == 403
    result = client.post('/auth/workspace', json={'role':'candidate'}, headers={'X-Session-Scope':'admin','X-CSRF-Token':staff['csrf_token']})
    assert result.status_code == 403 and result.json()['detail']['code'] == 'ADMIN_WORKSPACE_FIXED'
    assert client.post('/auth/admin/logout', headers={'X-CSRF-Token':staff['csrf_token'],'Origin':'https://other.example'}).status_code == 403
    assert client.get('/auth/me').json()['user'] == user
    assert client.get('/auth/admin/me').json() == staff


def test_staff_credentials_on_user_portal_never_issue_management_privileges(browser):
    client, user, resume, staff = browser
    result = client.post('/auth/login/password', json={'phone': STAFF_PHONE, 'password': PASSWORD, 'role':'candidate'})
    assert result.status_code == 200 and result.json()['user']['role'] == 'candidate'
    assert result.json()['user']['session_scope'] == 'user'
    assert client.get('/config/packs').status_code == 403
    assert client.get('/auth/admin/me').json() == staff
    with TestClient(client.app) as ordinary:
        ordinary.cookies.set(COOKIE, client.cookies.get(COOKIE))
        assert ordinary.get('/admin/overview').status_code == 401
        assert ordinary.get('/config/packs', headers={'X-Session-Scope':'admin'}).status_code == 401


def test_password_reset_revokes_both_scopes_of_same_account_but_not_other_accounts(browser):
    client, user, resume, staff = browser
    with TestClient(client.app) as staff_user:
        result = staff_user.post('/auth/login/password', json={'phone':STAFF_PHONE,'password':PASSWORD,'role':'candidate'})
        assert result.status_code == 200
        auth = client.app.state.auth
        with auth.tx() as cx: cx.execute('DELETE FROM limits')
        client.post('/auth/sms/send', json={'phone':STAFF_PHONE,'purpose':'reset'})
        result = client.post('/auth/admin/password/reset', json={'phone':STAFF_PHONE,'code':auth.sms.codes[STAFF_PHONE],'password':'Updated-staff-password-2026'})
        assert result.status_code == 200 and result.json()['user']['role'] == 'admin'
        assert staff_user.get('/auth/me').status_code == 401
        assert client.get('/auth/me').json()['user'] == user
        assert client.get('/admin/overview').status_code == 200


def test_legacy_session_migration_preserves_users_and_rejects_old_staff_user_cookie(tmp_path):
    settings = Settings(data_dir=tmp_path, env='demo', auto_seed=False)
    stamp = time.time()
    with sqlite3.connect(tmp_path/'auth.sqlite3') as cx:
        cx.execute('CREATE TABLE accounts (id TEXT PRIMARY KEY,env TEXT NOT NULL,phone TEXT NOT NULL,role TEXT NOT NULL,actor TEXT NOT NULL UNIQUE,created_at REAL NOT NULL,password_hash TEXT,UNIQUE(env,phone))')
        cx.execute('CREATE TABLE sessions (token_hash TEXT PRIMARY KEY,account_id TEXT NOT NULL,csrf TEXT NOT NULL,expires_at REAL NOT NULL,workspace_role TEXT NOT NULL)')
        for id, role, phone in [('user','candidate',USER_PHONE), ('staff','admin',STAFF_PHONE)]:
            cx.execute('INSERT INTO accounts VALUES (?,?,?,?,?,?,?)',(id,'demo',phone,role,role+':original',stamp,'preserved-hash'))
            cx.execute('INSERT INTO sessions VALUES (?,?,?,?,?)',(digest(id+'-token'),id,id+'-csrf',stamp+3600,'candidate' if id=='user' else 'enterprise'))
    app = create_app(settings)
    with TestClient(app) as client:
        client.cookies.set(COOKIE, 'user-token')
        assert client.get('/auth/me').json()['user']['actor'] == 'candidate:original'
        client.cookies.set(COOKIE, 'staff-token')
        assert client.get('/auth/me').status_code == 401 and client.get('/admin/overview').status_code == 401
        client.cookies.set(ADMIN_COOKIE, 'staff-token')
        assert client.get('/auth/admin/me').json()['user']['role'] == 'admin'
        Auth(settings); Auth(settings)
        assert client.get('/admin/overview').status_code == 200
        with app.state.auth.tx() as cx:
            assert {r['password_hash'] for r in cx.execute('SELECT * FROM accounts')} == {'preserved-hash'}
            assert {r['session_scope'] for r in cx.execute('SELECT * FROM sessions')} == {'user','admin'}
