"""An explicit HTTP deployment retains prod data scope and session protections."""
import pytest
from fastapi.testclient import TestClient
from app.auth import COOKIE, ADMIN_COOKIE
from app.main import create_app
from app.settings import Settings
from auth_helpers import FakeSMS, sign_in


def test_cookie_security_defaults_and_invalid_override(tmp_path, monkeypatch):
    monkeypatch.delenv('SESSION_COOKIE_SECURE', raising=False)
    settings = Settings(data_dir=tmp_path, env='prod', auto_seed=False)
    assert settings.session_cookie_secure is True
    settings.env = 'demo'
    assert settings.session_cookie_secure is False
    monkeypatch.setenv('SESSION_COOKIE_SECURE', 'typo')
    with pytest.raises(ValueError, match='SESSION_COOKIE_SECURE'):
        Settings(data_dir=tmp_path, env='prod')


def test_explicit_http_login_logout_and_scope_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv('SESSION_COOKIE_SECURE', 'false')
    settings = Settings(data_dir=tmp_path, env='prod', auto_seed=False)
    app = create_app(settings)
    app.state.auth.sms = FakeSMS()
    with TestClient(app, base_url='http://testserver') as client:
        user = sign_in(client, '13800000981')
        response = client.post('/auth/login/password', json={'phone':'13800000981','password':'Scenario-password-2026'})
        assert response.status_code == 200
        cookie = response.headers['set-cookie']
        assert COOKIE + '_http=' in cookie
        assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Secure' not in cookie
        client.headers['X-CSRF-Token'] = response.json()['csrf_token']
        assert client.get('/auth/me').json()['user']['id'] == user['id']
        assert client.get('/auth/admin/me').status_code == 401
        assert client.post('/auth/logout', headers={'Origin':'http://foreign.test'}).status_code == 403
        assert client.get('/auth/me').status_code == 200
        response = client.post('/auth/logout')
        assert response.status_code == 200
        assert 'Max-Age=0' in response.headers['set-cookie'] and 'Secure' not in response.headers['set-cookie']
        assert client.get('/auth/me').status_code == 401
        # HTTP uses separate cookie names, so an old HTTPS cookie cannot replace it.
        client.cookies.set(COOKIE, 'old-secure-token')
        assert client.get('/auth/me').status_code == 401
        with app.state.auth.tx() as cx:
            cx.execute("UPDATE accounts SET role='admin' WHERE id=?", (user['id'],))
        response = client.post('/auth/admin/login/password', json={'phone':'13800000981','password':'Scenario-password-2026'})
        assert response.status_code == 200
        assert ADMIN_COOKIE + '_http=' in response.headers['set-cookie']
        assert client.get('/auth/admin/me').status_code == 200
        assert client.get('/auth/me').status_code == 401
