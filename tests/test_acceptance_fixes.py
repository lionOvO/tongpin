"""Regressions for the independently reproduced 2026-10-14 acceptance defects."""
import asyncio
import copy
import time
import httpx
import pytest
from pydantic import ValidationError
from app.ai_workspace import AIWorkspace
from app.models import JobProfile
from app.security import redact
from app.errors import DomainError
from test_hiring import scene, apply_body, change
from test_platform_admin import clients as staff_clients, REASON, PASSWORD
from test_auth_isolation import create_job, create_resume, preferences
from test_enterprise_verification import submit


@pytest.mark.parametrize('private', ['男\n26岁\n138-0000-0000', '女，25岁，138 0000 0000', '性别：女｜年龄：24｜13800000000'])
def test_redaction_covers_unlabelled_and_inline_pii_preserving_work(private):
    work='本科 软件工程\n使用 Python 开发接口，负责参数校验与接口测试。'
    safe=redact(private+'\n'+work)
    assert safe.endswith(work)
    assert not any(v in safe for v in ['男','女','26岁','25岁','24','138'])
    sources,_=AIWorkspace.sources({'text':private+'\n'+work},None,[])
    assert all('138' not in s['text'] and '岁' not in s['text'] for s in sources)


def test_staff_user_scope_cannot_read_foreign_proof_and_admin_scope_is_audited(staff_clients):
    staff,enterprise,candidate,guest,*_=staff_clients
    submission=submit(candidate).json()['submission']
    url=f"/enterprise-verification/{submission['id']}/files/license"
    assert candidate.get(url).status_code==200
    login=staff.post('/auth/login/password',headers={'X-Session-Scope':'user'},json={'phone':'13800000903','password':PASSWORD,'role':'enterprise'})
    assert login.status_code==200 and login.json()['user']['session_scope']=='user'
    assert staff.get(url,headers={'X-Session-Scope':'user'}).status_code==404
    assert enterprise.get(url).status_code==404
    assert staff.get(url).status_code==200
    with staff.app.state.auth.tx() as cx:
        assert cx.execute("SELECT COUNT(*) FROM platform_admin_events WHERE action='下载企业证明'").fetchone()[0]==1


def test_preference_share_is_exact_version_and_revoke_blocks_future_reads(scene):
    app,a,b,c,d,guest,users,job,resume=scene
    preferences(a,'enterprise',job['id']);preferences(c,'candidate',resume['id'])
    body={'job_id':job['id'],'resume_id':resume['id']}
    old=c.post('/matches/run',json={**body,'share_with_job':True}).json()
    newer=preferences(c,'candidate',resume['id'])
    assert a.post('/matches/run',json=body).json()['cand_submission_id']==old['cand_submission_id']
    assert c.post('/matches/run',json=body).status_code==403
    assert c.post('/matches/run',json={**body,'share_with_job':True}).json()['cand_submission_id']==newer['id']
    row=c.post('/applications',json=apply_body(job,resume,share_preferences=True)).json()
    unsynced=preferences(c,'candidate',resume['id'])
    assert a.post('/matches/run',json=body).json()['cand_submission_id']==unsynced['id']
    row=change(c,row,'refresh_preferences').json()
    assert a.post('/matches/run',json=body).json()['cand_submission_id']==unsynced['id']
    change(c,row,'withdraw')
    preferences(c,'candidate',resume['id'])
    assert a.post('/matches/run',json=body).status_code==404
    assert a.get('/matches/'+old['id']).json()['cand_submission_id']==old['cand_submission_id']
    assert b.get('/matches').json()==[]


def test_clarification_changes_training_coverage_and_report_context(scene):
    app,a,b,c,d,guest,users,job,resume=scene
    answers={'purpose':'支持新业务','success':'独立负责交付','essential':'核心技术栈','trainable':'技术细节','source':'业务需要'}
    brief=a.post('/requirements/brief',json={'job_id':job['id'],'answers':answers}).json()
    skills=[r for r in brief['requirements'] if r['origin']=='JD原文']
    assert skills and all(r['type']=='可培养' and r['priority']=='P2' for r in skills)
    coverage=a.get('/requirements/coverage/'+job['id']).json()
    assert coverage['uncovered'] and all(not r['assessable'] for r in coverage['uncovered'])
    overrides=[{'skill':skills[0]['content'],'type':'硬性','priority':'P0'}]
    response=a.post('/requirements/brief',json={'job_id':job['id'],'answers':{**answers,'purpose':'人员补充'},'requirement_overrides':overrides})
    assert response.status_code==200
    fresh=response.json(); assert fresh['requirements']!=brief['requirements']
    imported=create_resume(a)
    report=app.state.service.evaluate(job,app.state.service.db.get('resumes',imported['id']),users[0]['actor'])
    assert report['hiring_brief_snapshot']['id']==fresh['id']
    assert report['skill_levels'][0]['hard'] is True
    assert any(q['type']=='需要沟通确认' for q in report['open_questions'])
    invalid=a.post('/requirements/brief',json={'job_id':job['id'],'requirement_overrides':[{'skill':'Unlisted','type':'硬性','priority':'P0'}]})
    assert invalid.status_code==422
    updated=a.put('/jobs/'+job['id']+'/confirm',json={'profile':job['profile'],'expected_version':job['version']}).json()
    assert app.state.service.current_brief(updated) is None


def test_duplicates_rejected_and_legacy_duplicates_cannot_inflate_samples(scene):
    app,a,b,c,d,guest,users,job,resume=scene
    profile=copy.deepcopy(job['profile']); profile['requirements']=[profile['requirements'][0]]*20
    with pytest.raises(ValidationError): JobProfile.model_validate(profile)
    assert a.put('/jobs/'+job['id']+'/confirm',json={'profile':profile,'expected_version':job['version']}).status_code==422
    svc=app.state.service
    svc.db.insert('role_benchmarks',{'skill':profile['requirements'][0]['skill'],'sample_size':20,
        'rubric_version':svc.config.get('rubric')['version'],'upper_level':3},users[0]['actor'],job['data_origin'],job_id=job['id'])
    assert a.get('/fit/benchmark?job_id='+job['id']).status_code==422
    assert svc.diagnose(job,users[0]['actor'])['benchmark_available'] is False
    svc.db.update('job_profiles',job['id'],{'profile':profile})
    assert svc.build_benchmark(job['id'],users[0]['actor'])['records']==[]
    with svc.db.transaction() as cx:
        for _ in range(19): svc.db.insert('job_profiles',{**job,'profile':profile},users[0]['actor'],job['data_origin'],cx=cx)
    records=svc.build_benchmark(job['id'],users[0]['actor'])['records']
    assert len(records)==1 and records[0]['sample_size']==20
    assert len(set(records[0]['sample_job_ids']))==20
    assert len(a.get('/fit/benchmark?job_id='+job['id']).json())==1


def test_candidate_jd_failure_has_evidence_checked_manual_fallback(scene,monkeypatch):
    app,a,b,c,d,guest,users,job,resume=scene
    def failed(*args): raise DomainError('AGENT_FAILED','Synthetic model failure',502)
    monkeypatch.setattr(app.state.service.gateway,'jd',failed)
    body={'resume_id':resume['id'],'title':'本人参照岗位','jd':'后端开发，需要使用 Python 编写业务接口。'}
    result=c.post('/fit/analyze',json=body)
    assert result.status_code==502 and result.json()['detail']['code']=='JD_PARSE_FAILED'
    profile={'direction':'后端开发','education':None,'requirements':[{'skill':'Python','required_level':2,'hard':True,'quote':'使用 Python 编写业务接口'}]}
    result=c.post('/fit/analyze',json={**body,'manual_profile':profile})
    assert result.status_code==200,result.text
    private=result.json()['job_id']
    assert a.get('/fit/benchmark?job_id='+private).status_code==404
    invalid=copy.deepcopy(profile);invalid['requirements'][0]['quote']='并不存在的原文'
    assert c.post('/fit/analyze',json={**body,'manual_profile':invalid}).status_code==422
    assert c.post('/fit/analyze',json={**body,'resume_id':create_resume(a)['id'],'manual_profile':profile}).status_code==404


def test_quality_counts_latest_reports_and_human_changes_without_personal_text(scene):
    app,a,b,c,d,guest,users,job,resume=scene
    imported=create_resume(a)
    body={'job_id':job['id'],'resume_ids':[imported['id']]}
    first=a.post('/assessments',json=body).json()['reports'][0]
    second=a.post('/assessments',json=body).json()['reports'][0]
    svc=app.state.service
    svc.db.insert('review_events',{'action':'单维改档','reason':'私密测试原因'},users[0]['actor'],job['data_origin'],report_id=second['id'])
    summary=a.get('/quality/summary?job_id='+job['id']).json()
    assert summary['reports_total']==1 and summary['historical_reports']==2
    assert summary['human_change_rate']==1 and summary['manually_changed_reports']==1
    assert sum(r['generated'] for r in summary['trend'])==2
    assert not any(v in str(summary) for v in ['私密测试原因', imported['display_name'], imported['text']])
    assert b.get('/quality/summary?job_id='+job['id']).status_code==404
    assert c.get('/quality/summary?job_id='+job['id']).status_code==403
    svc.db.update('ability_reports',second['id'],{'status':'已打回'})
    assert a.get('/quality/summary?job_id='+job['id']).json()['reports_total']==0


def test_initial_screen_uses_job_skills_and_same_quotes_as_report(scene):
    app,a,b,c,d,guest,users,_,_=scene
    profile={'direction':'后端开发','education':None,'requirements':[{'skill':'Rust','required_level':2,'quote':'熟悉 Rust','hard':True}]}
    row=a.post('/jobs',json={'title':'Rust 业务开发','jd':'后端开发工程师，需要熟悉 Rust，负责接口实现与服务交付。','manual_profile':profile}).json()
    job=a.put('/jobs/'+row['id']+'/confirm',json={'profile':profile,'expected_version':row['version']}).json()
    resume=a.post('/resumes',json={'name':'合成 Rust 简历','text':'本科软件工程。使用 Rust 实现后台接口功能，完成服务模块交付。'}).json()
    batch=a.post('/batches/run',json={'job_id':job['id']}).json()[0]
    result=app.state.service.evaluate(job,app.state.service.db.get('resumes',resume['id']),users[0]['actor'])
    assert batch['hits'][0]['skill']=='Rust' and result['skill_levels'][0]['evidence_level']>=2
    assert batch['hits'][0]['evidence']==result['skill_levels'][0]['evidence']


def test_pagination_search_and_unread_cover_more_than_1000_applications(scene):
    app,a,b,c,d,guest,users,job,resume=scene
    svc=app.state.service
    row=c.post('/applications',json=apply_body(job,resume)).json()
    raw=svc.db.get('applications',row['id'])
    with svc.db.transaction() as cx:
        svc.db.update('applications',row['id'],{'status':'accepted','updated_at':'2020-01-01',
            'messages':[{'side':'candidate','text':'唯一旧会话检索词','created_at':'2020-01-01'}]},cx)
        cx.execute('UPDATE applications SET created_at=? WHERE id=?',('2020-01-01',row['id']))
        for _ in range(1000): svc.db.insert('applications',raw,users[0]['actor'],job['data_origin'],cx=cx,job_id=job['id'],resume_id=resume['id'])
    first=a.get('/applications/page').json()
    assert first['total']==1001 and len(first['items'])==30
    last=a.get('/applications/page?offset=990').json()
    assert row['id'] in {r['id'] for r in last['items']}
    found=a.get('/messages/conversations/page?q=唯一旧会话检索词').json()
    assert found['total']==1 and found['items'][0]['id']==row['id'] and found['unread_total']==1
    assert b.get('/applications/page').json()['total']==0
    assert a.get('/applications/page?limit=101').status_code==422


def test_pdf_parsing_does_not_block_other_requests_and_page_limit_is_enforced(scene,monkeypatch):
    app,a,b,c,d,guest,users,job,resume=scene
    class Page:
        def extract_text(self): time.sleep(.6); return '使用 Python 编写后台接口并负责校验与测试。'
    class PDF:
        def __init__(self,*args): self.pages=[Page()]
    monkeypatch.setattr('app.main.PdfReader',PDF)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver',headers=dict(c.headers),cookies=dict(c.cookies)) as client:
            start=time.monotonic()
            async def health():
                await asyncio.sleep(.05)
                assert (await client.get('/health')).status_code==200
                return time.monotonic()-start
            upload,elapsed=await asyncio.gather(client.post('/resumes/batch',files={'files':('synthetic.pdf',b'%PDF','application/pdf')}),health())
            assert elapsed < .4 and upload.json()['resumes']
    asyncio.run(scenario())
    class TooManyPages:
        def __init__(self,*args): self.pages=[Page()]*51
    monkeypatch.setattr('app.main.PdfReader',TooManyPages)
    error=c.post('/resumes/batch',files={'files':('too-many.pdf',b'%PDF','application/pdf')}).json()
    assert not error['resumes'] and '50 页' in error['errors'][0]['message']


def test_pdf_timeout_keeps_concurrency_slots_until_finished_and_never_writes_late(scene,monkeypatch):
    app,a,b,c,d,guest,users,job,resume=scene
    class Page:
        def extract_text(self): time.sleep(.3); return '使用 Python 维护业务接口并负责校验与测试。'
    class PDF:
        def __init__(self,*args): self.pages=[Page()]
    monkeypatch.setattr('app.main.PdfReader',PDF)
    original_wait=asyncio.wait_for
    async def short_wait(future,timeout): return await original_wait(future,min(timeout,.08))
    monkeypatch.setattr('app.main.asyncio.wait_for',short_wait)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver',headers=dict(c.headers),cookies=dict(c.cookies)) as client:
            before=len((await client.get('/resumes')).json())
            async def upload(): return (await client.post('/resumes/batch',files={'files':('synthetic.pdf',b'%PDF','application/pdf')})).json()
            results=await asyncio.gather(upload(),upload(),upload())
            assert all(not result['resumes'] for result in results)
            errors=str(results)
            assert '超时' in errors and '任务较多' in errors
            await asyncio.sleep(.4)
            assert len((await client.get('/resumes')).json())==before
            monkeypatch.setattr('app.main.asyncio.wait_for',original_wait)
            assert (await upload())['resumes']
    asyncio.run(scenario())


def test_admin_governance_is_cross_enterprise_audited_and_not_available_to_user_scope(staff_clients):
    staff,enterprise,candidate,guest,company,*_=staff_clients
    job=create_job(enterprise);svc=staff.app.state.service
    svc.db.audit('Agent 调用',{'agent':'Evaluation','cost_cny':.125,'prompt':'private-test-input','api_key':'private-test-key'},company['actor'])
    jobs=staff.get('/admin/governance/jobs').json()
    assert job['id'] in {r['id'] for r in jobs['items']}
    summary=staff.get('/admin/governance/audit').json()
    assert summary['cost_cny']==.125 and any(r['owner']==company['actor'] for r in summary['logs'])
    assert 'private-test' not in str(summary)
    assert staff.get('/jobs').json()==[] and candidate.get('/admin/governance/jobs').status_code in {401,403}
    ordinary=guest.post('/auth/login/password',json={'phone':'13800000903','password':PASSWORD,'role':'enterprise'})
    assert ordinary.status_code==200 and ordinary.json()['user']['session_scope']=='user'
    assert guest.get('/admin/governance/jobs').status_code==401
    assert staff.post(f"/admin/governance/jobs/{job['id']}/benchmark",json={'reason':'x'}).status_code==422
    assert staff.post(f"/admin/governance/jobs/{job['id']}/benchmark",json=REASON).json()['records']==[]
    assert staff.post(f"/admin/governance/jobs/{job['id']}/resume",json=REASON).status_code==200
    assert staff.post(f"/admin/governance/jobs/{job['id']}/drift",json=REASON).json()['skipped'] is True
    assert enterprise.get('/jobs').json()[0]['id']==job['id']
    with staff.app.state.auth.tx() as cx:
        assert cx.execute('SELECT COUNT(*) FROM platform_admin_events').fetchone()[0]>=5
