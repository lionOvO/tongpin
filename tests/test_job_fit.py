"""Candidate fit tiers and async comparisons, isolated data and local demo rules only."""
import time
import threading
from uuid import uuid4
import pytest
from app.job_fit import fit_summary, rank_results, FIT_POLICY
from app.errors import DomainError
from test_hiring import scene
from test_auth_isolation import create_job, create_resume


def dimension(id, tier='B4', **extra):
    return dict(dimension_id=id, name={'D3': '项目经验', 'D4': '技能证据', 'D2': '学业表现'}[id],
                tier=tier, evidence=[] if tier == 'insufficient' else ['合成经历原文'], **extra)


@pytest.mark.parametrize('tier,band', [('B5','very_high'),('B4','high'),('B3','medium'),('B2','low'),('B1','very_low')])
def test_five_fit_bands_use_known_evidence_only(tier,band):
    summary=fit_summary([dimension('D4',tier),dimension('D3','insufficient'),dimension('D2','insufficient')],[])
    assert summary['band']==band
    assert summary['coverage']=={'known':1,'total':2}
    assert summary['missing']==['项目经验']
    assert summary['additional_missing']==['学业表现']


def test_missing_skills_do_not_count_as_low_or_block_a_known_project():
    dims=[dimension('D4','B1',rationale='部分证据不足'),dimension('D3','B4')]
    known={'skill':'Python','hard':True,'tier':'B4','evidence':['使用 Python 开发并交付接口']}
    unknown={'skill':'Docker','hard':True,'tier':'insufficient','evidence':[]}
    result=fit_summary(dims,[known,unknown])
    assert result['band']=='high'
    assert result['coverage']=={'known':2,'total':3}
    assert result['missing']==['Docker']
    assert result['assessed_items']==['Python','项目经验']
    assert fit_summary(dims,[unknown])['band']=='high'
    assert fit_summary([dimension('D3','insufficient')],[unknown])['band']=='unassessed'


def test_ordinal_median_uses_actual_skills_without_double_counting_d4():
    dims=[dimension('D4','B5'),dimension('D3','B3')]
    skill={'skill':'Python','hard':True,'tier':'B4','evidence':['合成技能依据']}
    result=fit_summary(dims,[skill])
    assert result['band']=='medium' and result['coverage']['known']==2
    skill['tier_range']=['B2','B3']
    assert fit_summary(dims,[skill])['band']=='low'
    dims[1]['evidence']=[]
    assert fit_summary(dims,[skill])['band']=='low'
    skill['evidence']=[]
    assert fit_summary(dims,[skill])['band']=='unassessed'
    # A fully known legacy D4 is usable only when no individual skill rows exist.
    assert fit_summary(dims,[])['band']=='very_high'
    dims[0]['rationale']='部分证据不足'
    assert fit_summary(dims,[])['band']=='unassessed'


def test_same_band_is_tied_and_old_missing_sentinels_do_not_break_the_tie():
    def row(band,name,old_key=0):
        return dict(name=name,fit_summary={'band':band},sort_key={'qualified_dims':old_key,'ordered_tiers':[old_key],'evidenced_dims':old_key})
    inputs=[row('unassessed','unknown'),row('very_low','very-low'),row('high','one'),row('high','two',999),
            row('medium','medium'),row('very_high','top'),row('low','low')]
    result=rank_results(inputs)
    assert [r['name'] for r in result]==['top','one','two','medium','low','very-low','unknown']
    assert [r['rank'] for r in result]==[1,2,2,4,5,6,None]
    assert all('rank' not in r for r in inputs)


def test_only_unknown_information_is_neutral_not_a_sixth_fit_band():
    result=fit_summary([dimension('D4','insufficient'),dimension('D3','insufficient')],[])
    assert result['band']=='unassessed' and result['coverage']['known']==0
    assert result['label']=='暂无判断依据' and '补充' not in result['reason']


def personal_job(scene):
    job = scene[7]
    return scene[0].state.service.db.insert('job_profiles', {k:v for k,v in job.items() if k not in {'id','owner','env','created_at'}}, scene[6][2]['actor'])


def body(scene, **patch):
    return dict(resume_id=scene[8]['id'], job_ids=[scene[7]['id']], request_id=str(uuid4()), **patch)


def finished(client, id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get('/compare/tasks/' + id)
        assert response.status_code == 200, response.text
        row = response.json()
        if row['status'] not in {'queued','running'}: return row
        time.sleep(.01)
    raise AssertionError('comparison did not finish')


def test_background_deduplication_progress_direct_model_and_private_state(scene, monkeypatch):
    app, a, _, c, _, _, *_ = scene
    calls = []; gate = threading.Event(); entered = threading.Event()
    original = app.state.service.evaluate
    def wait(*args):
        calls.append(1); entered.set(); assert gate.wait(5)
        return original(*args)
    monkeypatch.setattr(app.state.service, 'evaluate', wait)
    data = body(scene)
    start = time.monotonic(); response = c.post('/compare/tasks', json=data)
    assert response.status_code == 202, response.text
    assert time.monotonic() - start < 2
    row = response.json()
    try:
        assert entered.wait(2)
        assert row['total'] == 1 and row['model']['id'] == 'deepseek'
        assert not {'targets','resume_snapshot','owner','fingerprint'} & row.keys()
        assert c.post('/compare/tasks', json=data).json()['id'] == row['id']
        assert c.post('/compare/tasks', json={**data, 'request_id':str(uuid4())}).json()['id'] == row['id']
        other_job = personal_job(scene)
        assert c.post('/compare/tasks', json={**data, 'job_ids':[other_job['id']]}).status_code == 409
        assert c.post('/compare/tasks', json={**data, 'request_id':str(uuid4()), 'job_ids':[other_job['id']]}).status_code == 409
    finally: gate.set()
    result = finished(c, row['id'])
    assert result['status'] == 'completed', result
    assert result['processed'] == 1 and result['ranked_results'][0]['fit_summary']['band'] in {'very_high','high','medium','low','very_low','unassessed'}
    assert result['ranked_results'][0]['company_name'] == '合成测试企业'
    assert len(calls) == 1 and not app.state.service.db.list('fit_reports')
    assert c.post('/compare/tasks', json=data).json()['id'] == row['id']
    assert c.get('/compare/runs').json()[0]['id'] == row['id']


def test_comparison_permissions_validation_and_preflight(scene, monkeypatch):
    app, a, b, c, d, guest, *_ = scene
    data = body(scene)
    assert c.post('/compare/tasks', json=data, headers={'X-CSRF-Token':'wrong'}).status_code == 403
    assert a.post('/compare/tasks', json=data).status_code == 403
    assert guest.post('/compare/tasks', json=data).status_code == 401
    assert d.post('/compare/tasks', json=data).status_code == 404
    private = create_job(b)
    assert c.post('/compare/tasks', json={**data, 'job_ids':[scene[7]['id'], private['id']]}).status_code == 404
    assert not app.state.service.db.list('job_comparison_runs')
    for patch in [{'job_ids':[]}, {'job_ids':[scene[7]['id']]*2}, {'job_texts':['完整合成岗位描述，要求使用 Python 开发接口并参与项目协作。']}, {'job_ids':['bad']*21}]:
        assert c.post('/compare/tasks', json={**data, **patch}).status_code == 422
    row = c.post('/compare/tasks', json=data).json()
    finished(c,row['id'])
    assert d.get('/compare/tasks/'+row['id']).status_code == 404
    assert d.get('/compare/runs').json() == []


@pytest.mark.parametrize('mutation,code', [('hidden','JOB_UNAVAILABLE'),('job','JOB_CHANGED'),('resume','RESUME_CHANGED'),('deleted','NOT_FOUND')])
def test_material_changes_during_analysis_never_save_stale_result(scene, monkeypatch, mutation, code):
    app, a, _, c, _, _, *_ = scene
    svc = app.state.service; original = svc.evaluate
    def change(*args):
        result = original(*args)
        if mutation == 'hidden': svc.db.update('job_profiles',scene[7]['id'],{'published':False})
        elif mutation == 'job': svc.db.update('job_profiles',scene[7]['id'],{'version':scene[7]['version'] + 1})
        elif mutation == 'resume': svc.db.update('resumes',scene[8]['id'],{'text':'更新后的合成简历正文'})
        else: assert c.delete('/resumes/'+scene[8]['id']).status_code == 200
        return result
    monkeypatch.setattr(svc,'evaluate',change)
    response = c.post('/compare/tasks',json=body(scene)); assert response.status_code == 202,response.text
    row = finished(c,response.json()['id'])
    assert row['status'] == 'failed' and row['ranked_results'] == []
    assert row['errors'][0]['code'] == code


def test_partial_results_and_legacy_pasted_api_and_restart(scene, monkeypatch):
    app, _, _, c, *_ = scene
    personal = personal_job(scene); original = app.state.service.evaluate
    def fail_one(job,*args):
        if job['id'] == personal['id']: raise DomainError('AI_PROVIDER_TIMEOUT','合成测试超时',502)
        return original(job,*args)
    monkeypatch.setattr(app.state.service,'evaluate',fail_one)
    data = body(scene);data['job_ids'].append(personal['id'])
    row = finished(c,c.post('/compare/tasks',json=data).json()['id'])
    assert row['status'] == 'partial' and len(row['ranked_results']) == 1 and row['processed'] == 2
    assert row['errors'][0]['code'] == 'AI_PROVIDER_TIMEOUT'
    text = '合成后端岗位，要求本科，熟悉 Python 与 FastAPI，负责 API 服务及项目交付。'
    response = c.post('/compare/rank',json={'resume_id':scene[8]['id'],'job_texts':[text,text]})
    assert response.status_code == 200,response.text
    assert len(response.json()['ranked_results']) == 2
    stale = app.state.service.db.insert('job_comparison_runs',{'resume_name':'合成简历','status':'running','processed':0,'total':1,'ranked_results':[],'errors':[]},scene[6][2]['actor'],resume_id=scene[8]['id'])
    app.state.comparison_tasks.close();app.state.comparison_tasks.start()
    assert c.get('/compare/tasks/'+stale['id']).json()['status'] == 'interrupted'


def test_single_fit_report_includes_same_band_policy(scene):
    _, _, _, c, *_ = scene
    response = c.post('/fit/analyze',json={'resume_id':scene[8]['id'],'job_id':scene[7]['id']})
    assert response.status_code == 200,response.text
    assert response.json()['fit_summary']['policy_version'] == FIT_POLICY


def test_pasted_jd_also_uses_explicit_deepseek_and_budget_precedes_parsing(scene, monkeypatch):
    app, _, _, c, *_ = scene
    seen = []
    def parse(text, **kwargs):
        seen.append(kwargs['model_id'])
        raise DomainError('SYNTHETIC_STOP', '合成测试停止解析', 502)
    monkeypatch.setattr(app.state.service.gateway, 'jd', parse)
    text = '合成后端岗位，要求本科，熟悉 Python 与 FastAPI，负责业务接口项目交付。'
    data = {'resume_id':scene[8]['id'],'job_texts':[text,text],'request_id':str(uuid4())}
    row = finished(c,c.post('/compare/tasks',json=data).json()['id'])
    assert row['status'] == 'failed' and seen == ['deepseek','deepseek']
    seen.clear()
    monkeypatch.setattr(app.state.service.settings,'budget',0)
    data['request_id'] = str(uuid4())
    row = finished(c,c.post('/compare/tasks',json=data).json()['id'])
    assert row['errors'][0]['code'] == 'COST_BUDGET' and seen == []



def test_retry_only_missing_jobs_merges_successes_and_is_idempotent(scene,monkeypatch):
    app,_,_,c,d,guest,*_ = scene
    svc=app.state.service; personal=personal_job(scene); original=svc.evaluate
    calls=[]; fail=True
    def evaluate(job,*args):
        calls.append(job['id'])
        if fail and job['id']==personal['id']: raise DomainError('AGENT_FAILED','合成校验失败',502)
        return original(job,*args)
    monkeypatch.setattr(svc,'evaluate',evaluate)
    data=body(scene); data['job_ids'].append(personal['id'])
    first=finished(c,c.post('/compare/tasks',json=data).json()['id'])
    assert first['status']=='partial' and len(first['ranked_results'])==1
    endpoint='/compare/tasks/'+first['id']+'/retry'; retry={'request_id':str(uuid4())}
    assert d.post(endpoint,json=retry).status_code==404
    assert guest.post(endpoint,json=retry).status_code==401
    fail=False; calls.clear()
    response=c.post(endpoint,json=retry); assert response.status_code==202,response.text
    final=finished(c,response.json()['id'])
    assert final['status']=='completed' and final['processed']==final['total']==2
    assert final['errors']==[] and calls==[personal['id']]
    assert len(final['ranked_results'])==2 and final['retry_of']==first['id']
    preserved=next(r for r in final['ranked_results'] if r['job_ref']==1)
    assert preserved==first['ranked_results'][0]
    assert c.post(endpoint,json=retry).json()['id']==final['id']
    assert len(calls)==1
    assert c.get('/compare/tasks/'+first['id']).json()['status']=='partial'
    assert c.post('/compare/tasks/'+final['id']+'/retry',json={'request_id':str(uuid4())}).status_code==409
    svc.db.update('resumes',scene[8]['id'],{'text':scene[8]['text']+' 合成新增经历'})
    assert c.post(endpoint,json={'request_id':str(uuid4())}).status_code==409


def test_saved_comparisons_are_reclassified_without_models_or_snapshot_changes(scene,monkeypatch):
    app,_,_,c,*_=scene
    svc=app.state.service
    def no_call(*args,**kwargs): raise AssertionError('Historical reads must not call a model')
    monkeypatch.setattr(svc,'evaluate',no_call)
    base={'job_ref':1,'job_title':'合成历史岗位','dimensions':[dimension('D4','B1',rationale='部分证据不足'),dimension('D3','insufficient')],
          'skill_levels':[{'skill':'Python','hard':True,'tier':'B4','evidence':['使用 Python 交付业务接口']},
                          {'skill':'Docker','hard':True,'tier':'insufficient','evidence':[]}],
          'sort_key':{'qualified_dims':0,'ordered_tiers':[0],'evidenced_dims':0},
          'fit_summary':{'band':'insufficient','label':'待补充'},'rank':None}
    payload={'resume_name':'合成简历','status':'completed','processed':1,'total':1,'ranked_results':[base],'errors':[],'policy_version':'job-fit-evidence-v1'}
    stored=svc.db.insert('job_comparison_runs',payload,scene[6][2]['actor'],resume_id=scene[8]['id'])
    for result in [c.get('/compare/tasks/'+stored['id']).json(),c.get('/compare/runs').json()[0]]:
        assert result['ranked_results'][0]['fit_summary']['band']=='high'
        assert result['ranked_results'][0]['rank']==1
        assert result['ranked_results'][0]['fit_summary']['coverage']=={'known':1,'total':3}
        assert result['display_policy_version']==FIT_POLICY and result['policy_updated']
        assert not {'targets','resume_snapshot','owner','fingerprint'} & result.keys()
    assert svc.db.get('job_comparison_runs',stored['id'])['ranked_results']==[base]
