"""Registration, password authentication and additive legacy-account migration."""
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from app.auth import Auth, COOKIE
from app.main import create_app
from app.settings import Settings
from app.passwords import hash_password, verify_password
from auth_helpers import FakeSMS, approve_enterprise_fixture

PASSWORD = 'A secure password 2026'


@pytest.fixture
def clients(tmp_path):
    app = create_app(Settings(data_dir=tmp_path,env='dev',auto_seed=False))
    app.state.auth.sms = FakeSMS()
    with TestClient(app) as a, TestClient(app) as b:
        yield a,b,app.state.auth


def code_for(client,phone,purpose):
    auth = client.app.state.auth
    with auth.tx() as cx:
        cx.execute('DELETE FROM codes WHERE phone=?',(phone,))
        cx.execute('DELETE FROM limits')
    result=client.post('/auth/sms/send',json={'phone':phone,'purpose':purpose})
    assert result.status_code==200,result.text
    assert 'code' not in result.json()
    return auth.sms.codes[phone]


def register(client,phone='13800000301',role='enterprise'):
    code=code_for(client,phone,'register')
    response=client.post('/auth/register',json={'phone':phone,'code':code,'password':PASSWORD,'role':role})
    assert response.status_code==200,response.text
    client.headers['X-CSRF-Token']=response.json()['csrf_token']
    user=response.json()['user']
    return approve_enterprise_fixture(client,user) if role=='enterprise' else user


def test_registration_requires_sms_and_password_and_never_leaks_hash(clients):
    a,b,auth=clients
    payload={'phone':'13800000301','password':PASSWORD,'role':'enterprise','code':'123456'}
    assert a.post('/auth/register',json=payload).status_code==400
    assert a.post('/auth/register',json={k:v for k,v in payload.items() if k!='code'}).status_code==422
    user=register(a)
    assert user['has_password'] is True
    assert set(user)=={'id','actor','role','workspace_role','available_roles','enterprise_status','name','has_password','session_scope'}
    with auth.tx() as cx:
        row=auth.account(cx,payload['phone'])
    assert PASSWORD not in row['password_hash'] and row['password_hash'].startswith('scrypt$')
    assert PASSWORD not in a.get('/auth/me').text
    assert 'password_hash' not in a.get('/auth/me').text


def test_password_login_preserves_owner_and_role_and_isolates_accounts(clients):
    a,b,auth=clients
    original=register(a)
    job=a.post('/jobs',json={'title':'密码账号岗位','jd':'本科，熟悉 Python 与 FastAPI，负责 API 服务开发。'}).json()
    a.post('/auth/logout')
    result=a.post('/auth/login/password',json={'phone':'13800000301','password':PASSWORD})
    assert result.status_code==200
    assert result.json()['user']==original
    assert a.get('/jobs').json()[0]['id']==job['id']
    candidate=a.post('/auth/login/password',json={'phone':'13800000301','password':PASSWORD,'role':'candidate'})
    assert candidate.status_code==200 and candidate.json()['user']['id']==original['id']
    assert a.get('/jobs').json()==[]
    assert a.get('/jobs/'+job['id']+'/profile').status_code==404
    register(b,'13800000302')
    b.post('/auth/logout')
    assert b.post('/auth/login/password',json={'phone':'13800000302','password':PASSWORD}).status_code==200
    assert b.get('/jobs').json()==[]
    assert b.get('/jobs/'+job['id']+'/profile').status_code==404


def test_unknown_sms_login_never_creates_an_account(clients):
    a,b,auth=clients
    phone='13800000309';code=code_for(a,phone,'login')
    response=a.post('/auth/login/phone',json={'phone':phone,'code':code})
    assert response.status_code==400 and response.json()['detail']['code']=='ACCOUNT_NOT_REGISTERED'
    with auth.tx() as cx: assert auth.account(cx,phone) is None
    assert a.get('/auth/me').status_code==401


def test_wrong_password_and_unknown_account_share_error_and_are_rate_limited(clients):
    a,b,auth=clients
    register(a)
    a.post('/auth/logout')
    wrong=a.post('/auth/login/password',json={'phone':'13800000301','password':'Wrong password'})
    unknown=a.post('/auth/login/password',json={'phone':'13800000309','password':'Wrong password'})
    assert wrong.status_code==unknown.status_code==400
    assert wrong.json()==unknown.json()
    for _ in range(9):
        assert a.post('/auth/login/password',json={'phone':'13800000301','password':'Wrong password'}).status_code==400
    assert a.post('/auth/login/password',json={'phone':'13800000301','password':PASSWORD}).status_code==429
    Auth(auth.settings)  # Counters survive restart.
    assert a.post('/auth/login/password',json={'phone':'13800000301','password':PASSWORD}).status_code==429


def test_codes_are_bound_to_register_login_and_reset(clients):
    a,b,auth=clients
    register(a)
    phone='13800000301';code=code_for(b,phone,'login')
    reset={'phone':phone,'code':code,'password':'New password 2026'}
    assert b.post('/auth/password/reset',json=reset).status_code==400
    assert b.post('/auth/register',json={**reset,'role':'candidate'}).status_code==400
    assert b.post('/auth/login/phone',json={'phone':phone,'code':code,'role':'candidate'}).json()['user']['role']=='candidate'
    code=code_for(b,phone,'reset')
    assert b.post('/auth/login/phone',json={'phone':phone,'code':code}).status_code==400
    assert b.post('/auth/password/reset',json={**reset,'code':code}).status_code==200
    assert b.post('/auth/password/reset',json={**reset,'code':code}).status_code==400


def test_duplicate_registration_cannot_replace_password_role_or_data(clients):
    a,b,auth=clients
    original=register(a)
    code=code_for(b,'13800000301','register')
    assert b.post('/auth/register',json={'phone':'13800000301','code':code,'password':'Attacker password','role':'candidate'}).status_code==409
    result=b.post('/auth/login/password',json={'phone':'13800000301','password':PASSWORD})
    assert result.status_code==200 and result.json()['user']==original


def test_reset_revokes_all_old_sessions_preserves_records_and_changes_password(clients):
    a,b,auth=clients
    original=register(a)
    job=a.post('/jobs',json={'title':'保留的岗位','jd':'本科，熟悉 Python，负责 API 开发。'}).json()
    assert b.post('/auth/login/password',json={'phone':'13800000301','password':PASSWORD}).status_code==200
    new_password='  新的密码 with spaces  '
    code=code_for(b,'13800000301','reset')
    response=b.post('/auth/password/reset',json={'phone':'13800000301','code':code,'password':new_password})
    assert response.status_code==200 and response.json()['user']['id']==original['id']
    assert a.get('/auth/me').status_code==401
    assert b.get('/jobs').json()[0]['id']==job['id']
    assert a.post('/auth/login/password',json={'phone':'13800000301','password':PASSWORD}).status_code==400
    assert a.post('/auth/login/password',json={'phone':'13800000301','password':new_password.strip()}).status_code==400
    assert a.post('/auth/login/password',json={'phone':'13800000301','password':new_password}).status_code==200


@pytest.mark.parametrize('password',['short',' '*8,'x'*129])
def test_password_policy_is_enforced_server_side(clients,password):
    a,b,auth=clients
    assert a.post('/auth/register',json={'phone':'13800000301','code':'123456','role':'candidate','password':password}).status_code==422
    assert a.post('/auth/login/password',json={'phone':'13800000301','password':password}).status_code==422


def test_password_auth_checks_origin_and_secure_cookie(clients):
    a,b,auth=clients
    register(a)
    assert b.post('/auth/login/password',json={'phone':'13800000301','password':PASSWORD},headers={'Origin':'https://evil.example'}).status_code==403


def test_legacy_schema_migrates_without_replacing_account_and_can_set_password(tmp_path):
    settings=Settings(data_dir=tmp_path,env='dev',auto_seed=False)
    with sqlite3.connect(tmp_path/'auth.sqlite3') as cx:
        cx.execute('CREATE TABLE accounts (id TEXT PRIMARY KEY,env TEXT NOT NULL,phone TEXT NOT NULL,role TEXT NOT NULL,actor TEXT NOT NULL UNIQUE,created_at REAL NOT NULL,UNIQUE(env,phone))')
        cx.execute('INSERT INTO accounts VALUES (?,?,?,?,?,?)',('legacy','dev','13800000301','enterprise','enterprise:legacy',time.time()))
        cx.execute('CREATE TABLE codes (env TEXT NOT NULL,phone TEXT NOT NULL,sent_at REAL NOT NULL,expires_at REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,ready INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(env,phone))')
    app=create_app(settings);app.state.auth.sms=FakeSMS()
    with TestClient(app) as client:
        assert client.post('/auth/login/password',json={'phone':'13800000301','password':PASSWORD}).status_code==400
        code=code_for(client,'13800000301','login')
        user=client.post('/auth/login/phone',json={'phone':'13800000301','code':code}).json()['user']
        assert user['id']=='legacy' and user['has_password'] is False
        code=code_for(client,'13800000301','reset')
        result=client.post('/auth/password/reset',json={'phone':'13800000301','code':code,'password':PASSWORD})
        assert result.status_code==200
        assert result.json()['user']['id']=='legacy' and result.json()['user']['actor']=='candidate:legacy'
        assert result.json()['user']['has_password'] is True
        assert client.post('/auth/login/password',json={'phone':'13800000301','password':PASSWORD}).status_code==200


def test_hashes_are_random_salted_and_support_long_unicode_passwords():
    password='密码 空格🔐'*16
    first=hash_password(password);second=hash_password(password)
    assert first!=second
    assert verify_password(password,first) and verify_password(password,second)
    assert not verify_password(password+'x',first)
    assert not verify_password(password,None)
