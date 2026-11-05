import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.auth import COOKIE, digest
from app.errors import DomainError
from auth_helpers import FakeSMS, sign_in


@pytest.fixture
def accounts(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, env='demo', auto_seed=False))
    app.state.auth.sms = FakeSMS()
    with TestClient(app) as a, TestClient(app) as b, TestClient(app) as c, TestClient(app) as guest:
        ua = sign_in(a, '13800000101', 'enterprise')
        ub = sign_in(b, '13800000102', 'enterprise')
        uc = sign_in(c, '13800000103', 'candidate')
        yield a, b, c, guest, ua, ub, uc


def create_job(client):
    row = client.post('/jobs', json={'title': '私有后端岗位', 'jd': '岗位要求：本科，熟悉 Python 与 FastAPI，负责后端 API 服务开发。', 'data_origin': 'real'}).json()
    response = client.put('/jobs/' + row['id'] + '/confirm', json={'profile': row['profile'], 'expected_version': row['version']})
    assert response.status_code == 200, response.text
    return response.json()


def create_resume(client):
    response = client.post('/resumes', json={'name': '隔离测试简历', 'text': '专业：软件工程，本科\nGPA 3.6/4.0\n主导校园项目，使用 Python 与 FastAPI 构建交易服务。', 'data_origin': 'real'})
    assert response.status_code == 200, response.text
    return response.json()


def preferences(client, side, id):
    cfg = client.get('/config/preferences').json()
    dims = {d['id']: d['options'][0] for d in cfg['dimensions']}
    response = client.post('/preferences/submit', json={'side': side, 'job_id' if side == 'enterprise' else 'resume_id': id, 'dimensions': dims, 'dimension_version': cfg['version'], 'share_with_counterparty': True})
    assert response.status_code == 200, response.text
    return response.json()


def test_guest_cannot_access_data_even_with_forged_demo_header(accounts):
    a,b,c,guest,*users = accounts
    for path in ['/jobs', '/resumes', '/assessments', '/preferences', '/matches', '/config/packs', '/audit/export', '/memory']:
        assert guest.get(path, headers={'X-Demo-Actor': users[0]['actor']}).status_code == 401


def test_same_role_accounts_cannot_read_modify_or_export_each_others_data(accounts):
    a,b,c,guest,ua,ub,uc = accounts
    job = create_job(a); resume = create_resume(a)
    report = a.post('/assessments', json={'job_id':job['id'], 'resume_ids':[resume['id']]}).json()['reports'][0]
    preferences(a, 'enterprise', job['id'])
    assert b.get('/jobs', headers={'X-Demo-Actor':ua['actor']}).json() == []
    assert b.get('/resumes').json() == []
    assert b.get('/assessments').json() == []
    assert b.get('/preferences').json() == []
    for path in ['/jobs/'+job['id']+'/profile', '/assessments/'+report['id'], '/candidates/ranking?job_id='+job['id'], '/candidates/export?job_id='+job['id'], '/batches?job_id='+job['id']]:
        assert b.get(path).status_code == 404
    assert b.put('/jobs/'+job['id']+'/visibility',json={'published':True}).status_code == 404
    assert b.put('/jobs/'+job['id']+'/confirm',json={'profile':job['profile'], 'expected_version':job['version']}).status_code == 404
    assert b.post('/assessments', json={'job_id':job['id'], 'resume_ids':[resume['id']]}).status_code == 404
    assert b.post('/reviews', json={'report_id':report['id'], 'action':'确认', 'reason':'伪造审阅'}).status_code == 404
    assert b.get('/audit/summary').json()['logs'] == []


def test_candidate_can_only_use_explicitly_published_foreign_jobs(accounts):
    a,b,c,guest,*users = accounts
    job = create_job(a); resume = create_resume(c)
    assert c.get('/jobs').json() == []
    assert c.get('/jobs/'+job['id']+'/profile').status_code == 404
    assert c.get('/fit/benchmark?job_id='+job['id']).status_code == 404
    assert c.post('/fit/analyze',json={'job_id':job['id'], 'resume_id':resume['id']}).status_code == 404
    assert a.put('/jobs/'+job['id']+'/visibility',json={'published':True}).status_code == 200
    assert c.get('/jobs/'+job['id']+'/profile').status_code == 200
    assert 'history' not in c.get('/jobs/'+job['id']+'/profile').json()
    assert b.get('/jobs/'+job['id']+'/profile').status_code == 404
    fit = c.post('/fit/analyze',json={'job_id':job['id'], 'resume_id':resume['id']})
    assert fit.status_code == 200, fit.text
    assert a.get('/resumes').json() == []
    assert a.get('/fit/reports').status_code == 403
    a.put('/jobs/'+job['id']+'/visibility',json={'published':False})
    assert c.get('/jobs/'+job['id']+'/profile').status_code == 404


def test_sharing_is_scoped_to_a_specific_job_and_does_not_share_full_resume(accounts):
    a,b,c,guest,*users = accounts
    job = create_job(a); other = create_job(b); resume = create_resume(c)
    for client,j in [(a,job),(b,other)]:
        client.put('/jobs/'+j['id']+'/visibility',json={'published':True})
        preferences(client,'enterprise',j['id'])
    preferences(c,'candidate',resume['id'])
    assert a.get('/matches/participants?job_id='+job['id']).json() == []
    assert a.post('/matches/run',json={'job_id':job['id'], 'resume_id':resume['id']}).status_code == 404
    assert c.post('/matches/run',json={'job_id':job['id'], 'resume_id':resume['id']}).status_code == 403
    match = c.post('/matches/run',json={'job_id':job['id'], 'resume_id':resume['id'], 'share_with_job':True}).json()
    assert a.get('/matches/'+match['id']).status_code == 200
    assert b.get('/matches/'+match['id']).status_code == 404
    assert len(a.get('/matches/participants?job_id='+job['id']).json()) == 1
    assert b.get('/matches/participants?job_id='+other['id']).json() == []
    assert b.post('/matches/run',json={'job_id':other['id'], 'resume_id':resume['id'], 'share_with_job':True}).status_code == 404
    assert a.get('/resumes').json() == []
    assert a.post('/assessments',json={'job_id':job['id'], 'resume_ids':[resume['id']]}).status_code == 404


def test_global_configuration_and_purge_require_admin(accounts):
    a,b,c,guest,*users = accounts
    cfg = a.get('/config/presentation').json()
    for client in [a,b,c]:
        assert client.get('/config/packs').status_code == 403
        assert client.put('/config/presentation',json=cfg).status_code == 403
        assert client.post('/config/packs/import',json={}).status_code == 403
        assert client.post('/maintenance/purge',json={'env':'demo','confirmation':'清理合成数据'}).status_code == 403
        assert client.post('/demo/seed').status_code == 403


def test_csrf_origin_cookie_and_session_revocation(accounts):
    a,b,c,guest,*users = accounts
    cookie = a.cookies.get(COOKIE)
    a.headers.pop('X-CSRF-Token')
    assert a.post('/jobs',json={'title':'后端岗位','jd':'熟悉 Python 与 MySQL，负责后端 API 与数据存储服务。'}).status_code == 403
    csrf = a.get('/auth/me').json()['csrf_token']; a.headers['X-CSRF-Token'] = csrf
    assert a.post('/auth/logout',headers={'Origin':'https://evil.example'}).status_code == 403
    assert a.post('/auth/logout').status_code == 200
    assert a.get('/jobs').status_code == 401
    assert guest.get('/jobs',headers={'Cookie':COOKIE+'='+cookie}).status_code == 401


def test_login_selects_workspace_without_changing_account_identity(accounts):
    a,b,c,guest,ua,*users = accounts
    auth=a.app.state.auth
    with auth.tx() as cx: cx.execute('DELETE FROM codes'); cx.execute('DELETE FROM limits')
    user = sign_in(a, '13800000101', 'candidate')
    assert user['role'] == 'candidate' and user['id'] == ua['id']
    assert user['actor'] != ua['actor']
    with auth.tx() as cx:
        account=auth.account(cx,'13800000101')
        assert account['actor']==ua['actor'] and account['role']=='enterprise'
    assert len(a.app.state.auth.sms.calls) == 4


def test_codes_expire_attempts_persist_and_cannot_be_replayed(accounts):
    a,b,c,guest,*users = accounts
    auth = a.app.state.auth; phone='13800000104'
    sign_in(guest,phone)
    guest.post('/auth/logout')
    with auth.tx() as cx: cx.execute('DELETE FROM limits')
    assert guest.post('/auth/sms/send',json={'phone':phone}).status_code == 200
    correct=auth.sms.codes[phone]; wrong='999999' if correct != '999999' else '888888'
    for _ in range(5):
        assert guest.post('/auth/login/phone',json={'phone':phone,'code':wrong}).status_code == 400
    assert guest.post('/auth/login/phone',json={'phone':phone,'code':correct}).status_code == 400
    with auth.tx() as cx: cx.execute('DELETE FROM codes WHERE phone=?',(phone,));cx.execute('DELETE FROM limits')
    guest.post('/auth/sms/send',json={'phone':phone}); correct=auth.sms.codes[phone]
    with auth.tx() as cx: cx.execute('UPDATE codes SET expires_at=? WHERE phone=?',(time.time()-1,phone))
    assert guest.post('/auth/login/phone',json={'phone':phone,'code':correct}).status_code == 400
    with auth.tx() as cx: cx.execute('DELETE FROM codes WHERE phone=?',(phone,))
    guest.post('/auth/sms/send',json={'phone':phone}); correct=auth.sms.codes[phone]
    response=guest.post('/auth/login/phone',json={'phone':phone,'code':correct})
    assert response.status_code == 200
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
    assert guest.post('/auth/login/phone',json={'phone':phone,'code':correct}).status_code == 400
    with auth.tx() as cx:
        stored=cx.execute('SELECT token_hash FROM sessions WHERE account_id=?',(response.json()['user']['id'],)).fetchone()[0]
    assert stored == digest(guest.cookies.get(COOKIE)) and stored != guest.cookies.get(COOKIE)


def test_cooldown_and_rate_limit_survive_new_auth_instance(accounts):
    a,b,c,guest,*users = accounts
    from app.auth import Auth
    phone='13800000104'; auth=a.app.state.auth
    guest.post('/auth/sms/send',json={'phone':phone})
    assert guest.post('/auth/sms/send',json={'phone':phone}).status_code == 429
    restored=Auth(auth.settings);restored.sms=auth.sms
    a.app.state.auth=restored
    # Direct store check verifies persistence; route closures keep original service instance.
    from starlette.requests import Request
    from app.auth import SmsInput
    req=Request({'type':'http','method':'POST','headers':[], 'client':('testclient',123),'server':('testserver',80),'path':'/','scheme':'http','query_string':b''})
    with pytest.raises(DomainError) as error: restored.send(SmsInput(phone=phone),req)
    assert error.value.status == 429


def test_missing_sms_configuration_fails_closed(tmp_path):
    settings=Settings(data_dir=tmp_path,env='demo',auto_seed=False)
    settings.sms.update({name:'' for name in settings.sms if name.startswith('ALIBABA_')})
    with TestClient(create_app(settings)) as client:
        assert client.get('/auth/options').json()['sms_available'] is False
        assert client.post('/auth/sms/send',json={'phone':'13800000101'}).status_code == 503
        assert client.post('/auth/login/phone',json={'phone':'13800000101','code':'123456'}).status_code == 400
        assert client.get('/jobs').status_code == 401


def test_expired_sessions_and_forged_admin_roles_fail_closed(accounts):
    a,b,c,guest,*users = accounts
    assert guest.post('/auth/login/phone',json={'phone':'13800000105','code':'123456','role':'admin'}).status_code == 422
    with a.app.state.auth.tx() as cx: cx.execute('UPDATE sessions SET expires_at=? WHERE token_hash=?',(time.time()-1,digest(a.cookies.get(COOKIE))))
    assert a.get('/auth/me').status_code == 401
    assert a.get('/jobs').status_code == 401


def test_production_authenticated_access_and_secure_cookie(tmp_path):
    settings=Settings(data_dir=tmp_path,env='prod',auto_seed=False)
    app=create_app(settings);app.state.auth.sms=FakeSMS()
    with TestClient(app,base_url='https://testserver') as client:
        sign_in(client,'13800000101','enterprise')
        assert 'Secure' in client.cookies.jar._cookies['testserver.local']['/'][COOKIE]._rest or client.cookies.jar._cookies['testserver.local']['/'][COOKIE].secure
        job=create_job(client)
        assert client.get('/jobs').json()[0]['id']==job['id']


@pytest.mark.parametrize('scheme',['','同频登录'])
def test_sms_provider_never_returns_codes_or_retries_on_failure(tmp_path,monkeypatch,scheme):
    import httpx
    from app.sms import AliyunSMS
    settings=Settings(data_dir=tmp_path,env='dev',auto_seed=False)
    settings.sms.update({name:'test-value' for name in settings.sms if name.startswith('ALIBABA_')})
    settings.sms['scheme']=scheme
    calls=[]
    def transport(url,**kwargs):
        calls.append(kwargs)
        if kwargs['data']['Action']=='SendSmsVerifyCode': return httpx.Response(200,json={'Code':'OK','Success':True,'Model':{'VerifyCode':'123456','BizId':'business'}})
        return httpx.Response(200,json={'Code':'OK','Success':True,'Model':{'VerifyResult':'UNKNOWN'}})
    monkeypatch.setattr(httpx,'post',transport)
    sms=AliyunSMS(settings)
    assert sms.send('13800000101')=='business'
    assert sms.verify('13800000101','123456') is False
    assert calls[0]['data']['ReturnVerifyCode']=='false'
    assert calls[0]['data']['AutoRetry']=='0'
    assert calls[0]['data'].get('SchemeName')==calls[1]['data'].get('SchemeName')
    assert ('SchemeName' in calls[0]['data'])==bool(scheme)


def test_ai_audit_uses_authenticated_actor_and_not_shared_demo_owner(accounts,monkeypatch):
    a,b,c,guest,ua,ub,uc=accounts
    svc=a.app.state.service
    original=svc.gateway.jd
    def recorded(text):
        svc.record_call({'agent':'JD','cost_cny':0.01,'result':'正常'})
        return original(text)
    monkeypatch.setattr(svc.gateway,'jd',recorded)
    create_job(a);create_job(b)
    for client,user in [(a,ua),(b,ub)]:
        logs=client.get('/audit/summary').json()['logs']
        assert all(log['owner']==user['actor'] for log in logs)
        assert sum(log['event_type']=='Agent 调用' for log in logs)==1


def test_concurrent_code_consumption_only_issues_one_session(accounts):
    a,b,c,guest,*users=accounts
    phone='13800000109';auth=a.app.state.auth
    guest.post('/auth/sms/send',json={'phone':phone,'purpose':'register'});code=auth.sms.codes[phone]
    app=a.app
    def attempt():
        with TestClient(app) as client: return client.post('/auth/register',json={'phone':phone,'code':code,'password':'Concurrent-password','role':'candidate'}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor: statuses=list(executor.map(lambda _:attempt(),range(2)))
    assert sorted(statuses)==[200,400]
