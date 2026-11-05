"""Internal staff permissions never propagate to ordinary accounts or public resources."""
import pytest
from fastapi.testclient import TestClient
from app.auth import COOKIE
from app.main import create_app
from app.settings import Settings
from auth_helpers import FakeSMS, sign_in
from scripts.manage_accounts import promote
from test_auth_isolation import create_job, create_resume

PASSWORD='Scenario-password-2026'
REASON={'reason':'合成测试：核查异常资料后执行监管处理。'}


@pytest.fixture
def clients(tmp_path):
    app=create_app(Settings(data_dir=tmp_path,env='demo',auto_seed=False))
    app.state.auth.sms=FakeSMS()
    with TestClient(app) as staff,TestClient(app) as recruiter,TestClient(app) as candidate,TestClient(app) as guest:
        # Staff assignment is a server operator action, not a recruiter privilege.
        original=sign_in(staff,'13800000903','candidate')
        promote(app.state.auth,'13800000903')
        result=staff.post('/auth/admin/login/password',json={'phone':'13800000903','password':PASSWORD})
        assert result.status_code==200,result.text
        staff.headers['X-CSRF-Token']=result.json()['csrf_token']
        staff.headers['X-Session-Scope']='admin'
        company=sign_in(recruiter,'13800000901','enterprise')
        person=sign_in(candidate,'13800000902','candidate')
        yield staff,recruiter,candidate,guest,company,person,original


def test_separate_staff_login_rejects_normal_accounts_without_issuing_session(clients):
    staff,recruiter,candidate,guest,*_=clients
    for phone in ('13800000901','13800000902'):
        result=guest.post('/auth/admin/login/password',json={'phone':phone,'password':PASSWORD})
        assert result.status_code==403 and result.json()['detail']['code']=='ADMIN_REQUIRED'
        assert not result.headers.get('set-cookie') and guest.get('/auth/me').status_code==401
    auth=staff.app.state.auth
    guest.post('/auth/sms/send',json={'phone':'13800000902','purpose':'login'})
    result=guest.post('/auth/admin/login/phone',json={'phone':'13800000902','code':auth.sms.codes['13800000902']})
    assert result.status_code==403 and not result.headers.get('set-cookie')
    guest.post('/auth/sms/send',json={'phone':'13800000903','purpose':'login'})
    result=guest.post('/auth/admin/login/phone',json={'phone':'13800000903','code':auth.sms.codes['13800000903']})
    assert result.status_code==200 and result.json()['user']['role']=='admin'
    assert recruiter.get('/auth/me').json()['user']['role']=='enterprise'


def test_admin_routes_are_closed_to_guests_and_ordinary_users(clients):
    staff,recruiter,candidate,guest,*_=clients
    for client,status in ((guest,401),(candidate,401),(recruiter,401)):
        for path in ('/admin/overview','/admin/accounts','/admin/records/jobs','/admin/records/resumes','/admin/events','/admin/records/resumes/missing'):
            assert client.get(path,headers={'X-Demo-Actor':'admin:forged','X-Role':'admin'}).status_code==status
        for path in ('/admin/accounts/missing/suspend','/admin/jobs/missing/hide'):
            assert client.post(path,json=REASON).status_code==status


def test_staff_listings_are_bounded_masked_and_environment_scoped(clients):
    staff,recruiter,candidate,guest,*_=clients
    resume=create_resume(candidate)
    job=create_job(recruiter)
    svc=staff.app.state.service
    foreign=svc.db.insert('job_profiles',{'title':'other environment secret'},'enterprise:foreign')
    with svc.db.transaction() as cx: cx.execute("UPDATE job_profiles SET env='prod' WHERE id=?",(foreign['id'],))
    accounts=staff.get('/admin/accounts?limit=2').json()
    assert accounts['total']==3 and len(accounts['items'])==2
    assert 'password_hash' not in str(accounts) and '13800000901' not in str(accounts)
    assert all('****' in row['name'] for row in accounts['items'])
    jobs=staff.get('/admin/records/jobs').json()
    assert [j['id'] for j in jobs['items']]==[job['id']]
    assert 'source_jd' not in jobs['items'][0] and 'profile' not in jobs['items'][0]
    records=staff.get('/admin/records/resumes').json()
    assert records['items'][0]['id']==resume['id'] and 'text' not in records['items'][0]
    assert staff.get('/admin/records/jobs/'+foreign['id']).status_code==404
    for query in ('?limit=51','?limit=0','?offset=-1'):
        assert staff.get('/admin/accounts'+query).status_code==422
    assert staff.get('/admin/records/passwords').status_code==422
    assert staff.get('/admin/overview').json()['job_profiles']==1


def test_explicit_staff_private_access_is_logged_and_normal_ownership_unchanged(clients):
    staff,recruiter,candidate,guest,*_=clients
    resume=create_resume(candidate);job=create_job(recruiter)
    assert staff.get('/resumes').json()==[]
    assert recruiter.get('/resumes').json()==[]
    response=staff.get('/admin/records/resumes/'+resume['id'])
    assert response.status_code==200 and response.json()['text']==resume['text']
    assert 'owner' not in response.json()
    assert staff.get('/admin/records/jobs/'+job['id']).json()['source_jd']==job['source_jd']
    events=staff.get('/admin/events').json()['items']
    assert len(events)==2 and {e['resource_id'] for e in events}=={job['id'],resume['id']}
    assert all(e['action']=='查看资料' for e in events)
    assert candidate.get('/resumes').json()[0]['id']==resume['id']


def test_job_moderation_hides_public_job_and_blocks_republication_until_released(clients):
    staff,recruiter,candidate,guest,*_=clients
    job=create_job(recruiter);url='/jobs/'+job['id']+'/visibility'
    assert recruiter.put(url,json={'published':True}).status_code==200
    assert any(j['id']==job['id'] for j in candidate.get('/jobs').json())
    result=staff.post('/admin/jobs/'+job['id']+'/hide',json=REASON)
    assert result.status_code==200 and result.json()['published'] is False
    assert not candidate.get('/jobs').json()
    assert recruiter.put(url,json={'published':True}).json()['detail']['code']=='JOB_SUSPENDED'
    # Editing the job profile must preserve the restriction.
    current=recruiter.get('/jobs').json()[0]
    result=recruiter.put('/jobs/'+job['id']+'/confirm',json={'profile':current['profile'],'expected_version':current['version']})
    assert result.status_code==200 and result.json()['moderation_status']=='suspended'
    assert staff.post('/admin/jobs/'+job['id']+'/restore',json=REASON).status_code==200
    assert not candidate.get('/jobs').json()  # No automatic re-publication.
    assert recruiter.put(url,json={'published':True}).status_code==200
    assert candidate.get('/jobs').json()[0]['id']==job['id']
    assert len(staff.get('/admin/events').json()['items'])==2


def test_suspension_revokes_every_session_blocks_login_and_hides_company_jobs(clients):
    staff,recruiter,candidate,guest,company,*_=clients
    job=create_job(recruiter)
    recruiter.put('/jobs/'+job['id']+'/visibility',json={'published':True})
    auth=staff.app.state.auth
    with TestClient(staff.app) as another:
        response=another.post('/auth/login/password',json={'phone':'13800000901','password':PASSWORD,'role':'enterprise'})
        assert response.status_code==200
        old=another.cookies.get(COOKIE)
        assert staff.post('/admin/accounts/'+company['id']+'/suspend',json=REASON).status_code==200
        assert recruiter.get('/auth/me').status_code==401 and another.get('/auth/me').status_code==401
        assert not candidate.get('/jobs').json()
        result=another.post('/auth/login/password',json={'phone':'13800000901','password':PASSWORD})
        assert result.status_code==403 and result.json()['detail']['code']=='ACCOUNT_DISABLED'
        assert not result.headers.get('set-cookie')
        with auth.tx() as cx: cx.execute('DELETE FROM limits')
        another.post('/auth/sms/send',json={'phone':'13800000901','purpose':'login'})
        assert another.post('/auth/login/phone',json={'phone':'13800000901','code':auth.sms.codes['13800000901']}).status_code==403
        assert staff.post('/admin/accounts/'+company['id']+'/restore',json=REASON).status_code==200
        assert another.get('/auth/me').status_code==401
        result=another.post('/auth/login/password',json={'phone':'13800000901','password':PASSWORD})
        assert result.status_code==200 and another.cookies.get(COOKIE)!=old
        assert len(candidate.get('/jobs').json())==1
    assert auth.enterprise_owner_verified(company['actor'])


def test_moderation_requires_reason_csrf_origin_and_cannot_suspend_staff(clients):
    staff,recruiter,candidate,guest,company,*_=clients
    url='/admin/accounts/'+company['id']+'/suspend'
    for body in ({'reason':'短'}, {'reason':' '*10}, {'reason':REASON['reason'],'role':'admin'}):
        assert staff.post(url,json=body).status_code==422
    assert staff.post(url,json=REASON,headers={'X-CSRF-Token':'forged'}).status_code==403
    assert staff.post(url,json=REASON,headers={'Origin':'https://other.example'}).status_code==403
    own=staff.get('/auth/me').json()['user']['id']
    assert staff.post('/admin/accounts/'+own+'/suspend',json=REASON).json()['detail']['code']=='ADMIN_PROTECTED'
    assert staff.get('/admin/events').json()['total']==0
    assert staff.post('/admin/accounts/'+company['id']+'/delete',json=REASON).status_code==422


def test_server_assigned_staff_preserves_candidate_workspace_and_never_grants_public_promotion(clients):
    staff,recruiter,candidate,guest,company,person,original=clients
    auth=staff.app.state.auth
    with auth.tx() as cx:
        owner=cx.execute("SELECT actor FROM account_workspaces WHERE account_id=? AND role='candidate'",(original['id'],)).fetchone()[0]
        assert owner==original['actor']
    assert guest.post('/auth/register',json={'phone':'13800000904','code':'123456','password':PASSWORD,'role':'admin'}).status_code==422
    result=staff.post('/auth/workspace',json={'role':'candidate'})
    assert result.status_code==403 and result.json()['detail']['code']=='ADMIN_WORKSPACE_FIXED'
    normal=staff.post('/auth/login/password',json={'phone':'13800000903','password':PASSWORD,'role':'candidate'})
    assert normal.status_code==200 and normal.json()['user']['actor']==original['actor']
    assert normal.json()['user']['role']=='candidate'
    assert staff.get('/admin/overview').status_code==200


def test_staff_cannot_treat_personal_pasted_jd_as_recruiter_publication(clients):
    staff,recruiter,candidate,guest,company,person,*_=clients
    job=staff.app.state.service.db.insert('job_profiles',{'title':'个人对照 JD','published':False},person['actor'])
    assert staff.post('/admin/jobs/'+job['id']+'/hide',json=REASON).status_code==404
    assert staff.get('/admin/records/jobs/'+job['id']).json()['title']=='个人对照 JD'
