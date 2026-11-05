"""One verified account, two server-owned workspaces; no private data crosses roles."""
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from app.auth import Auth, COOKIE, digest
from app.main import create_app
from app.settings import Settings
from auth_helpers import FakeSMS, sign_in, approve_enterprise_fixture
from test_auth_isolation import create_job, create_resume, preferences


@pytest.fixture
def clients(tmp_path):
    settings=Settings(data_dir=tmp_path,env='demo',auto_seed=False)
    settings.llm_mode='demo'; settings.vector=False
    app=create_app(settings); app.state.auth.sms=FakeSMS()
    with TestClient(app) as a, TestClient(app) as b, TestClient(app) as guest:
        user=sign_in(a,'13800000601','enterprise')
        other=sign_in(b,'13800000602','candidate')
        yield a,b,guest,user,other


def switch(client,role):
    response=client.post('/auth/workspace',json={'role':role})
    assert response.status_code==200,response.text
    client.headers['X-CSRF-Token']=response.json()['csrf_token']
    return response.json()['user']


def test_two_workspaces_keep_jobs_resumes_reports_preferences_and_audit_private(clients):
    a,b,guest,enterprise,other=clients
    job=create_job(a); er=create_resume(a)
    report=a.post('/assessments',json={'job_id':job['id'],'resume_ids':[er['id']]}).json()['reports'][0]
    ep=preferences(a,'enterprise',job['id'])
    old_cookie=a.cookies.get(COOKIE); old_csrf=a.headers['X-CSRF-Token']
    candidate=switch(a,'candidate')
    assert candidate['id']==enterprise['id'] and candidate['name']==enterprise['name']
    assert candidate['actor']=='candidate:'+enterprise['id'] and candidate['workspace_role']=='candidate'
    assert set(candidate['available_roles'])=={'candidate','enterprise'}
    assert old_cookie!=a.cookies.get(COOKIE) and old_csrf!=a.headers['X-CSRF-Token']
    assert guest.get('/jobs',headers={'Cookie':COOKIE+'='+old_cookie}).status_code==401
    assert a.get('/jobs').json()==[] and a.get('/resumes').json()==[] and a.get('/preferences').json()==[]
    assert a.get('/assessments/'+report['id']).status_code==404
    assert a.put('/jobs/'+job['id']+'/visibility',json={'published':True}).status_code==403
    assert a.get('/fit/reports').json()==[]
    cr=create_resume(a); cp=preferences(a,'candidate',cr['id'])
    fit=a.post('/fit/analyze',json={'resume_id':cr['id'],'jd':job['source_jd']})
    assert fit.status_code==200,fit.text
    fit_ids={r['id'] for r in a.get('/fit/reports').json()}
    assert fit_ids
    assert a.get('/jobs').json()[0]['owner']==candidate['actor']  # own target JD, never the enterprise job
    assert a.get('/audit/summary').status_code==403
    logs=a.app.state.service.db.list('audit_logs',owner=candidate['actor'])
    assert logs and all(r['owner']==candidate['actor'] for r in logs)
    # Another account can use both roles, but neither workspace can see this account's records.
    assert b.get('/resumes').json()==[] and b.get('/fit/reports').json()==[]
    approve_enterprise_fixture(b,other)
    switch(b,'enterprise')
    assert b.get('/jobs').json()==[] and b.get('/assessments').json()==[]
    assert b.get('/assessments/'+report['id']).status_code==404
    restored=switch(a,'enterprise')
    assert restored==enterprise
    assert [r['id'] for r in a.get('/jobs').json()]==[job['id']]
    assert [r['id'] for r in a.get('/resumes').json()]==[er['id']]
    assert [r['id'] for r in a.get('/assessments').json()]==[report['id']]
    assert [r['id'] for r in a.get('/preferences').json()]==[ep['id']]
    assert a.get('/fit/reports').status_code==403
    assert a.post('/assessments',json={'job_id':job['id'],'resume_ids':[cr['id']]}).status_code==404
    switch(a,'candidate')
    assert [r['id'] for r in a.get('/resumes').json()]==[cr['id']]
    assert [r['id'] for r in a.get('/preferences').json()]==[cp['id']]
    assert {r['id'] for r in a.get('/fit/reports').json()}==fit_ids


def test_published_jobs_require_explicit_publication_even_between_own_workspaces(clients):
    a,b,guest,user,other=clients
    job=create_job(a)
    assert a.put('/jobs/'+job['id']+'/visibility',json={'published':True}).status_code==200
    switch(a,'candidate')
    public=a.get('/jobs/'+job['id']+'/profile')
    assert public.status_code==200
    assert 'owner' not in public.json() and 'history' not in public.json()
    assert a.put('/jobs/'+job['id']+'/confirm',json={'profile':job['profile'],'expected_version':job['version']}).status_code==403


def test_switch_requires_auth_csrf_origin_and_only_allows_business_roles(clients):
    a,b,guest,user,other=clients
    assert guest.post('/auth/workspace',json={'role':'candidate'}).status_code==401
    assert a.post('/auth/workspace',json={'role':'candidate'},headers={'X-CSRF-Token':'forged'}).status_code==403
    assert a.post('/auth/workspace',json={'role':'candidate'},headers={'Origin':'https://evil.example'}).status_code==403
    for payload in [{'role':'admin'},{'role':'candidate','actor':other['actor']},{'role':'enterprise','account_id':other['id']},{}]:
        assert a.post('/auth/workspace',json=payload).status_code==422
    assert a.get('/auth/me').json()['user']==user
    switch(a,'candidate')
    assert a.get('/config/packs').status_code==403


def test_switch_is_session_scoped_and_refresh_and_restart_keep_selected_role(clients):
    a,b,guest,user,other=clients
    response=guest.post('/auth/login/password',json={'phone':'13800000601','password':'Scenario-password-2026','role':'enterprise'})
    assert response.status_code==200
    candidate=switch(a,'candidate')
    assert a.get('/auth/me').json()['user']==candidate
    assert guest.get('/auth/me').json()['user']==user
    auth=Auth(a.app.state.auth.settings)
    from starlette.requests import Request
    req=Request({'type':'http','method':'GET','headers':[(b'cookie',(COOKIE+'='+a.cookies.get(COOKIE)).encode())], 'client':('testclient',123),'server':('testserver',80),'path':'/auth/me','scheme':'http','query_string':b''})
    assert auth.public(auth.session(req))==candidate
    # Logging out and selecting another role uses the same account and password, no second registration.
    assert a.post('/auth/logout').status_code==200
    response=a.post('/auth/login/password',json={'phone':'13800000601','password':'Scenario-password-2026','role':'candidate'})
    assert response.status_code==200 and response.json()['user']==candidate


def test_concurrent_switches_cannot_reuse_a_rotated_session(clients):
    a,b,guest,user,other=clients
    cookie=a.cookies.get(COOKIE); csrf=a.headers['X-CSRF-Token']
    def attempt(role):
        with TestClient(a.app) as client:
            return client.post('/auth/workspace',json={'role':role},headers={'Cookie':COOKIE+'='+cookie,'X-CSRF-Token':csrf}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses=list(executor.map(attempt,['candidate','enterprise']))
    assert sorted(statuses)==[200,401]


def test_migration_preserves_original_owner_password_and_existing_session(tmp_path):
    settings=Settings(data_dir=tmp_path,env='demo',auto_seed=False)
    stamp=time.time()
    with sqlite3.connect(tmp_path/'auth.sqlite3') as cx:
        cx.execute('CREATE TABLE accounts (id TEXT PRIMARY KEY,env TEXT NOT NULL,phone TEXT NOT NULL,role TEXT NOT NULL,actor TEXT NOT NULL UNIQUE,created_at REAL NOT NULL,password_hash TEXT,UNIQUE(env,phone))')
        cx.execute('INSERT INTO accounts VALUES (?,?,?,?,?,?,?)',('legacy','demo','13800000601','candidate','candidate:custom-legacy-owner',stamp,'existing-hash'))
        cx.execute('CREATE TABLE sessions (token_hash TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES accounts(id),csrf TEXT NOT NULL,expires_at REAL NOT NULL)')
        cx.execute('INSERT INTO sessions VALUES (?,?,?,?)',(digest('legacy-cookie'),'legacy','legacy-csrf',stamp+3600))
    app=create_app(settings)
    with TestClient(app) as client:
        client.cookies.set(COOKIE,'legacy-cookie');client.headers['X-CSRF-Token']='legacy-csrf'
        legacy=client.get('/auth/me').json()['user']
        assert legacy['actor']=='candidate:custom-legacy-owner' and legacy['workspace_role']=='candidate'
        resume=create_resume(client)
        approve_enterprise_fixture(client,legacy)
        assert switch(client,'enterprise')['actor']=='enterprise:legacy'
        assert client.get('/resumes').json()==[]
        Auth(settings); Auth(settings)  # Idempotent migrations never replace owners.
        assert switch(client,'candidate')['actor']==legacy['actor']
        assert client.get('/resumes').json()[0]['id']==resume['id']
        with app.state.auth.tx() as cx:
            account=app.state.auth.account(cx,'13800000601')
            assert tuple(account)[:7]==('legacy','demo','13800000601','candidate','candidate:custom-legacy-owner',stamp,'existing-hash')
            assert cx.execute('SELECT COUNT(*) FROM account_workspaces').fetchone()[0]==2


def test_admin_privileges_require_dedicated_scope_even_for_staff_accounts(clients):
    a,b,guest,user,other=clients
    from scripts.manage_accounts import promote
    promote(a.app.state.auth,'13800000601')
    response=a.post('/auth/login/password',json={'phone':'13800000601','password':'Scenario-password-2026','role':'enterprise'})
    assert response.status_code==200 and response.json()['user']['role']=='enterprise'
    a.headers['X-CSRF-Token']=response.json()['csrf_token']
    assert a.get('/config/packs').status_code==403
    assert switch(a,'candidate')['role']=='candidate'
    result=a.post('/auth/admin/login/password',json={'phone':'13800000601','password':'Scenario-password-2026'})
    assert result.status_code==200 and result.json()['user']['role']=='admin'
    a.headers['X-Session-Scope']='admin';a.headers['X-CSRF-Token']=result.json()['csrf_token']
    assert a.get('/config/packs').status_code==200
    assert a.post('/auth/workspace',json={'role':'candidate'}).status_code==403
    a.headers['X-Session-Scope']='user'
    assert a.get('/auth/me').json()['user']['role']=='candidate'
    assert a.get('/config/packs').status_code==403
