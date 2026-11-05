"""An ordinary verified phone is never sufficient for recruiter access."""
import base64
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from app.auth import COOKIE, digest, Auth
from app.main import create_app
from app.settings import Settings
from auth_helpers import FakeSMS, sign_in
from scripts.manage_accounts import promote
from test_auth_isolation import create_job, create_resume

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lQAAAABJRU5ErkJggg==')
FIELDS={'company_name':'合成测试企业有限公司','credit_code':'91310115MA1K123456','legal_representative':'合成法人','contact_name':'合成联系人'}


@pytest.fixture
def clients(tmp_path):
    settings=Settings(data_dir=tmp_path,env='demo',auto_seed=False)
    settings.llm_mode='demo';settings.vector=False
    app=create_app(settings);app.state.auth.sms=FakeSMS()
    with TestClient(app) as user,TestClient(app) as other,TestClient(app) as admin,TestClient(app) as guest:
        u=sign_in(user,'13800000701','candidate')
        v=sign_in(other,'13800000702','candidate')
        sign_in(admin,'13800000703','enterprise')
        promote(app.state.auth,'13800000703')
        response=admin.post('/auth/admin/login/password',json={'phone':'13800000703','password':'Scenario-password-2026','role':'enterprise'})
        assert response.status_code==200
        admin.headers['X-CSRF-Token']=response.json()['csrf_token']
        admin.headers['X-Session-Scope']='admin'
        yield user,other,admin,guest,u,v


def submit(client,fields=None,content=PNG,filename='license.png'):
    return client.post('/enterprise-verification',data=fields or FIELDS,files={'license':(filename,content,'image/png'),'authorization':('authorization.png',PNG,'image/png')})


def approve(admin,id):
    result=admin.post('/enterprise-reviews/'+id,json={'decision':'approve','reason':'合成测试：登记信息、执照及企业授权已人工核对一致。'})
    assert result.status_code==200,result.text
    return result.json()


def switch(client,role):
    result=client.post('/auth/workspace',json={'role':role})
    if result.status_code==200: client.headers['X-CSRF-Token']=result.json()['csrf_token']
    return result


def test_unverified_candidate_cannot_enter_create_publish_or_self_approve(clients):
    user,other,admin,guest,u,v=clients
    assert u['available_roles']==['candidate'] and u['enterprise_status']=='unsubmitted'
    assert switch(user,'enterprise').json()['detail']['code']=='ENTERPRISE_VERIFICATION_REQUIRED'
    assert user.post('/jobs',json={'title':'伪造企业岗位','jd':'熟悉 Python 与 FastAPI，负责后端 API 服务开发。'}).status_code==403
    assert user.get('/enterprise-reviews').status_code==401
    assert user.post('/enterprise-reviews/missing',json={'decision':'approve','reason':'自己填写审核通过'}).status_code==401
    assert guest.get('/enterprise-verification').status_code==401


def test_register_and_password_or_sms_login_cannot_bypass_qualification(clients):
    user,other,admin,guest,u,v=clients
    auth=user.app.state.auth;phone='13800000704'
    guest.post('/auth/sms/send',json={'phone':phone,'purpose':'register'})
    result=guest.post('/auth/register',json={'phone':phone,'code':auth.sms.codes[phone],'password':'Unverified-password','role':'enterprise'})
    assert result.status_code==200 and result.json()['user']['role']=='candidate'
    id=result.json()['user']['id']
    guest.headers['X-CSRF-Token']=result.json()['csrf_token']
    assert switch(guest,'enterprise').status_code==403
    guest.post('/auth/logout')
    result=guest.post('/auth/login/password',json={'phone':phone,'password':'Unverified-password','role':'enterprise'})
    assert result.status_code==200 and result.json()['user']['id']==id and result.json()['user']['workspace_role']=='candidate'
    with auth.tx() as cx: cx.execute('DELETE FROM codes');cx.execute('DELETE FROM limits')
    guest.post('/auth/sms/send',json={'phone':phone})
    result=guest.post('/auth/login/phone',json={'phone':phone,'code':auth.sms.codes[phone],'role':'enterprise'})
    assert result.status_code==200 and result.json()['user']['role']=='candidate'
    assert guest.get('/jobs').json()==[]


def test_private_evidence_pending_review_approval_and_separate_business_data(clients):
    user,other,admin,guest,u,v=clients
    resume=create_resume(user)
    result=submit(user)
    assert result.status_code==200,result.text
    submission=result.json()['submission'];id=submission['id']
    assert result.json()['status']=='pending'
    assert 'license_file' not in submission and 'account_id' not in submission
    assert switch(user,'enterprise').status_code==403
    assert user.get('/enterprise-verification').json()['submission']['id']==id
    assert other.get('/enterprise-verification').json()['submission'] is None
    assert submit(user).status_code==409
    for kind in ('license','authorization'):
        url=f'/enterprise-verification/{id}/files/{kind}'
        assert guest.get(url).status_code==401 and other.get(url).status_code==404
        for client in (user,admin):
            evidence=client.get(url)
            assert evidence.status_code==200 and evidence.content==PNG
            assert evidence.headers['content-disposition'].startswith('attachment;')
            assert evidence.headers['cache-control']=='no-store'
            assert evidence.headers['x-content-type-options']=='nosniff'
    assert any(r['id']==id for r in admin.get('/enterprise-reviews').json())
    approve(admin,id)
    me=user.get('/auth/me').json()['user']
    assert me['enterprise_status']=='approved' and me['available_roles']==['enterprise','candidate']
    assert switch(user,'enterprise').status_code==200
    assert user.get('/resumes').json()==[]
    job=create_job(user)
    assert switch(user,'candidate').status_code==200
    assert user.get('/jobs').json()==[]
    assert [r['id'] for r in user.get('/resumes').json()]==[resume['id']]
    assert user.get('/jobs/'+job['id']+'/profile').status_code==404
    admin_id=admin.get('/auth/me').json()['user']['id']
    with user.app.state.auth.tx() as cx:
        event=cx.execute('SELECT * FROM enterprise_review_events WHERE submission_id=?',(id,)).fetchone()
        assert event['decision']=='approve' and event['reviewer_id']==admin_id


def test_rejection_requires_reason_and_resubmission_never_reuses_previous_approval(clients):
    user,other,admin,guest,u,v=clients
    id=submit(user).json()['submission']['id']
    assert admin.post('/enterprise-reviews/'+id,json={'decision':'approve','reason':'     '}).status_code==422
    assert user.get('/enterprise-verification').json()['status']=='pending'
    result=admin.post('/enterprise-reviews/'+id,json={'decision':'reject','reason':'授权文件未能证明联系人有企业招聘授权，请补充。'})
    assert result.status_code==200
    assert switch(user,'enterprise').status_code==403
    fresh=submit(user).json()['submission']
    assert fresh['id']!=id and fresh['status']=='pending'
    assert admin.post('/enterprise-reviews/'+id,json={'decision':'approve','reason':'旧申请不能继续批准'}).status_code==409
    approve(admin,fresh['id'])
    assert submit(user).status_code==409


def test_revocation_invalidates_recruiter_sessions_and_hides_public_jobs(clients):
    user,other,admin,guest,u,v=clients
    id=submit(user).json()['submission']['id'];approve(admin,id)
    switch(user,'enterprise');job=create_job(user)
    assert user.put('/jobs/'+job['id']+'/visibility',json={'published':True}).status_code==200
    assert other.get('/jobs/'+job['id']+'/profile').status_code==200
    old_cookie=user.cookies.get(COOKIE)
    for reason in ('', '撤回', '     ', '   撤回   '):
        invalid=admin.post('/enterprise-reviews/'+id,json={'decision':'revoke','reason':reason})
        assert invalid.status_code==422
        assert next(row for row in admin.get('/enterprise-reviews').json() if row['id']==id)['status']=='approved'
        assert user.get('/jobs').status_code==200
        assert other.get('/jobs/'+job['id']+'/profile').status_code==200
    result=admin.post('/enterprise-reviews/'+id,json={'decision':'revoke','reason':'企业授权已撤回，暂停招聘方认证及公开岗位。'})
    assert result.status_code==200
    assert guest.get('/jobs',headers={'Cookie':COOKIE+'='+old_cookie}).status_code==401
    assert other.get('/jobs/'+job['id']+'/profile').status_code==404
    assert other.get('/jobs').json()==[]
    result=user.post('/auth/login/password',json={'phone':'13800000701','password':'Scenario-password-2026','role':'enterprise'})
    assert result.status_code==200 and result.json()['user']['role']=='candidate'
    user.headers['X-CSRF-Token']=result.json()['csrf_token']
    assert switch(user,'enterprise').status_code==403
    assert user.app.state.service.db.get('job_profiles',job['id'])['owner']=='enterprise:'+u['id']


@pytest.mark.parametrize('content,filename',[(b'not-an-image','fake.png'),(PNG,'fake.html'),(b'','empty.png'),(b'\x89PNG\r\n\x1a\n'+b'x'*(5*1024*1024),'huge.png')],ids=['invalid-image','wrong-extension','empty','oversized'])
def test_invalid_evidence_is_rejected_without_persisting_or_approving(clients,content,filename):
    user,other,admin,guest,u,v=clients
    result=submit(user,content=content,filename=filename)
    assert result.status_code==422
    assert user.get('/enterprise-verification').json()['status']=='unsubmitted'
    assert switch(user,'enterprise').status_code==403
    folder=user.app.state.auth.verification.folder
    assert not folder.exists() or not list(folder.iterdir())


def test_submission_and_review_check_csrf_and_origin(clients):
    user,other,admin,guest,u,v=clients
    csrf=user.headers.pop('X-CSRF-Token')
    assert submit(user).status_code==403
    user.headers['X-CSRF-Token']=csrf
    id=submit(user).json()['submission']['id']
    result=admin.post('/enterprise-reviews/'+id,json={'decision':'approve','reason':'需要核对真实企业授权'},headers={'Origin':'https://evil.example'})
    assert result.status_code==403
    assert user.get('/enterprise-verification').json()['status']=='pending'


def test_legacy_recruiter_is_gated_without_changing_account_or_deleting_owned_data(tmp_path):
    settings=Settings(data_dir=tmp_path,env='demo',auto_seed=False)
    stamp=time.time()
    with sqlite3.connect(tmp_path/'auth.sqlite3') as cx:
        cx.execute('CREATE TABLE accounts (id TEXT PRIMARY KEY,env TEXT NOT NULL,phone TEXT NOT NULL,role TEXT NOT NULL,actor TEXT NOT NULL UNIQUE,created_at REAL NOT NULL,password_hash TEXT,UNIQUE(env,phone))')
        cx.execute('INSERT INTO accounts VALUES (?,?,?,?,?,?,?)',('old','demo','13800000701','enterprise','enterprise:original',stamp,'existing-password-hash'))
        cx.execute('CREATE TABLE sessions (token_hash TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES accounts(id),csrf TEXT NOT NULL,expires_at REAL NOT NULL)')
        cx.execute('INSERT INTO sessions VALUES (?,?,?,?)',(digest('old-cookie'),'old','csrf',stamp+3600))
    app=create_app(settings)
    from app.models import JobInput
    job=app.state.service.create_job(JobInput(title='原招聘资料',jd='本科，熟悉 Python 与 FastAPI，负责后端 API 开发。'),'enterprise:original')
    with TestClient(app) as client:
        client.cookies.set(COOKIE,'old-cookie');client.headers['X-CSRF-Token']='csrf'
        user=client.get('/auth/me').json()['user']
        assert user['id']=='old' and user['workspace_role']=='candidate' and user['enterprise_status']=='unsubmitted'
        assert switch(client,'enterprise').status_code==403
        assert app.state.service.db.get('job_profiles',job['id'])['owner']=='enterprise:original'
        Auth(settings)
        with app.state.auth.tx() as cx:
            assert tuple(app.state.auth.account(cx,'13800000701'))[:7]==('old','demo','13800000701','enterprise','enterprise:original',stamp,'existing-password-hash')
