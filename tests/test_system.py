import copy
import json
import sqlite3
import pytest
from app.deterministic import skill_tier,median_tier,gpa_tier
from app.security import redact

CAND={"X-Demo-Actor":"candidate:lin"}
OTHER={"X-Demo-Actor":"candidate:zhou"}


def data(client):
    job=next(j for j in client.get('/jobs').json() if j['title']=='Python 后端工程师')
    resume=client.get('/resumes',headers=CAND).json()[0]
    return job,resume


@pytest.mark.parametrize('level,required,expected',[(4,2,'B5'),(3,3,'B4'),(2,3,'B3'),(2,4,'B2'),(1,4,'B1'),(0,2,'insufficient')])
def test_skill_mapping(level,required,expected):assert skill_tier(level,required)==expected


def test_missing_evidence_never_becomes_low():
    assert median_tier(['B4','insufficient'])=='B4'
    assert median_tier(['B4','B3'])=='B3'
    assert median_tier(['insufficient'])=='insufficient'


def test_gpa_not_fabricated_percentile():
    assert gpa_tier('GPA 3.5/4.0')['tier']=='B4'
    assert '非统计百分位' in gpa_tier('GPA 3.5/4.0')['rationale']
    assert gpa_tier('GPA 3.5')['tier']=='B3'
    assert gpa_tier('GPA 3.5/0') is None


def test_sanitization():
    text='姓名：张三\n性别：男\n年龄：24\n学校：甲大学\n婚育：未婚\n民族：汉\n专业：软件工程\n手机：13812345678\na@b.com\n课程项目使用 Python 实现统计'
    safe=redact(text)
    for item in ['张三','性别','年龄','甲大学','婚育','民族','13812345678','a@b.com']:assert item not in safe
    assert '软件工程' in safe and 'Python' in safe


def test_health_and_15_tables(client):
    assert client.get('/health').json()['status']=='ok'
    svc=client.app.state.service
    with svc.db.transaction() as cx:
        assert len(cx.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())==15
        assert not cx.execute('PRAGMA foreign_key_check').fetchall()


def test_matching_reproducible_and_quotes(client):
    j,r=data(client);body={'job_id':j['id'],'resume_id':r['id']}
    first=client.post('/matches/run',json=body).json()
    second=client.post('/matches/run',json=body,headers=CAND).json()
    assert first['id']==second['id']
    assert first['dimension_results']==second['dimension_results']
    assert first['overall_tier']=='高'
    assert all(d['ent_quote'] and d['cand_quote'] for d in first['dimension_results'])


def test_snapshots_immutable_and_missing_is_unknown(client):
    j,r=data(client)
    old=client.post('/matches/run',json={'job_id':j['id'],'resume_id':r['id']}).json()
    pref=client.get('/preferences',headers=CAND).json()[0]
    values=copy.deepcopy(pref['dimensions']);values['autonomy']=None
    payload={'side':'candidate','resume_id':r['id'],'dimensions':values,'dimension_version':pref['dimension_version'],'share_with_counterparty':True}
    assert client.post('/preferences/submit',json=payload,headers=CAND).status_code==200
    current=client.post('/matches/run',json={'job_id':j['id'],'resume_id':r['id']}).json()
    assert current['overall_tier']=='无法判断'
    assert next(d for d in current['dimension_results'] if d['dimension_id']=='autonomy')['tier']=='无法判断'
    historic=client.get('/matches/'+old['id']).json()
    assert historic['outdated'] and historic['cand_snapshot']['autonomy']!=None


def test_cross_side_access_denied(client):
    ent_report=client.get('/assessments').json()[0]
    assert client.get('/assessments/'+ent_report['id'],headers=CAND).status_code==404
    own=client.get('/resumes',headers=CAND).json()
    other=client.get('/resumes',headers=OTHER).json()
    assert set(r['id'] for r in own).isdisjoint(r['id'] for r in other)
    j,r=data(client)
    assert client.post('/matches/run',json={'job_id':j['id'],'resume_id':r['id']},headers=OTHER).status_code==404


def test_no_unconfirmed_ranking_and_review_lock(client):
    reports=client.get('/assessments').json();r=reports[0]
    assert client.get('/candidates/ranking?job_id='+r['job_id']).json()==[]
    assert client.post('/reviews',json={'report_id':r['id'],'action':'确认','reason':'原文依据已检查'}).status_code==200
    assert len(client.get('/candidates/ranking?job_id='+r['job_id']).json())==1
    change={'report_id':r['id'],'action':'单维改档','dimension_id':'D4','tier_after':'B3','reason':'重新对照原文'}
    assert client.post('/reviews',json=change).status_code==409
    assert client.post('/reviews',json={'report_id':r['id'],'action':'整份打回','reason':'重新检查原文'}).status_code==200
    assert client.get('/candidates/ranking?job_id='+r['job_id']).json()==[]


def test_cannot_upgrade_without_evidence(client):
    r=next(r for r in client.get('/assessments').json() if any(d['tier']=='insufficient' for d in r['dimensions']))
    d=next(d for d in r['dimensions'] if d['tier']=='insufficient')
    response=client.post('/reviews',json={'report_id':r['id'],'action':'单维改档','dimension_id':d['dimension_id'],'tier_after':'B4','reason':'手工判断'})
    assert response.status_code==422


def test_candidate_fit_hides_interview_questions(client):
    j,r=data(client)
    response=client.post('/fit/analyze',json={'job_id':j['id'],'resume_id':r['id']},headers=CAND)
    assert response.status_code==200
    report=response.json()
    assert 'open_questions' not in report
    assert all(d['tier']=='insufficient' or d['evidence'] for d in report['dimensions'])


def test_user_pasted_jd_private(client):
    _,r=data(client)
    jd='我的目标后端岗位\n岗位要求：熟悉 Python，熟练使用 MySQL，本科。'
    report=client.post('/fit/analyze',json={'resume_id':r['id'],'jd':jd,'title':'本人目标'},headers=CAND).json()
    assert report['job_title']=='本人目标'
    assert client.get('/jobs/'+report['job_id']+'/profile',headers=OTHER).status_code==404
    assert report['job_id'] not in {j['id'] for j in client.get('/jobs',headers=OTHER).json()}


def test_config_version_and_required_dimensions(client):
    cfg=client.get('/config/preferences').json()
    same=client.put('/config/preferences',json=cfg)
    assert same.status_code==400
    cfg['version']='pref-2.0';cfg['dimensions'][3]['required']=True
    assert client.put('/config/preferences',json=cfg).status_code==400


def test_expired_preference_version_blocked(client):
    j,r=data(client)
    cfg=client.get('/config/preferences').json();cfg['version']='pref-2.0'
    assert client.put('/config/preferences',json=cfg).status_code==200
    response=client.post('/matches/run',json={'job_id':j['id'],'resume_id':r['id']})
    assert response.status_code==400 and response.json()['detail']['code']=='DIMENSION_VERSION_EXPIRED'


def test_benchmark_low_sample_rejected(client):
    j,_=data(client)
    assert client.get('/fit/benchmark?job_id='+j['id'],headers=CAND).status_code==422
    assert client.post('/benchmarks/build',json={'job_id':j['id']}).json()['records']==[]


def test_profile_confirmation_version_conflict(client):
    j,_=data(client)
    response=client.put('/jobs/'+j['id']+'/confirm',json={'profile':j['profile'],'expected_version':1})
    assert response.status_code==409


def test_source_quote_rejection(client):
    j,_=data(client);profile=copy.deepcopy(j['profile']);profile['requirements'][0]['quote']='不存在的引用'
    assert client.put('/jobs/'+j['id']+'/confirm',json={'profile':profile,'expected_version':j['version']}).status_code==422


def test_no_fake_evaluation_metrics(client):
    result=client.post('/selfcheck/identifiability').json()
    assert '未加载人工标注集' in result['note']
    assert client.post('/audit/drift-check').json()['skipped']


def test_purge_backup_preserves_real_and_no_orphans(client):
    real=client.post('/resumes',json={'name':'真实数据占位','text':'专业：软件工程\n课程项目使用 Python 实现数据统计功能。','data_origin':'real'}).json()
    assert client.post('/maintenance/purge',json={'env':'prod','confirmation':'清理合成数据'}).status_code==400
    result=client.post('/maintenance/purge',json={'env':'demo','confirmation':'清理合成数据'})
    assert result.status_code==200
    assert [r['id'] for r in client.get('/resumes').json()]==[real['id']]
    assert client.get('/matches').json()==[]
    svc=client.app.state.service
    assert (svc.settings.data_dir/'backups'/result.json()['backup']).exists()
    with svc.db.transaction() as cx:assert not cx.execute('PRAGMA foreign_key_check').fetchall()


def test_pack_validates_all_before_write(client):
    pack=client.get('/config/packs').json()
    pack['configs']['priorities']['enabled']=[]
    assert client.post('/config/packs/import',json=pack).status_code==400
    assert client.get('/config/priorities').json()['enabled']


def test_presentation_can_change_with_version(client):
    cfg=client.get('/config/presentation').json();cfg['version']='presentation-2.0'
    assert client.put('/config/presentation',json=cfg).status_code==200
    cfg['version']='presentation-3.0';cfg['tier_labels']['B4']='匹配度 87%'
    assert client.put('/config/presentation',json=cfg).status_code==400


def test_file_failure_isolated(client):
    response=client.post('/resumes/batch',files=[('files',('bad.json',b'{bad','application/json')),('files',('good.txt','专业：软件工程\n课程项目使用 Python 实现后端功能。'.encode(),'text/plain'))])
    assert response.status_code==200
    assert len(response.json()['resumes'])==1 and len(response.json()['errors'])==1


def test_comparison_requires_two_jobs(client):
    _,r=data(client)
    assert client.post('/compare/rank',json={'resume_id':r['id'],'job_texts':['岗位要求熟悉 Python 后端开发。']},headers=CAND).status_code==422
    response=client.post('/compare/rank',json={'resume_id':r['id'],'job_texts':['后端工程师\n岗位要求：熟练 Python，熟悉 FastAPI。','前端工程师\n岗位要求：熟练 React，熟悉 TypeScript。']},headers=CAND)
    assert response.status_code==200 and len(response.json()['ranked_results'])==2


def test_missing_education_is_pending_not_pass_or_fail(client):
    j,_=data(client)
    resume=client.post('/resumes',json={'name':'缺少学历信息','text':'使用 Python 开发课程项目，并使用 MySQL 实现数据持久化。'}).json()
    rows=client.post('/batches/run',json={'job_id':j['id']}).json()
    row=next(r for r in rows if r['resume_id']==resume['id'])
    assert row['hard_gate_result']=='信息待补充' and row['hard_gate_rule_ids']==[]


def test_private_benchmark_access_is_denied(client):
    _,r=data(client)
    pasted=client.post('/fit/analyze',json={'resume_id':r['id'],'jd':'个人目标岗位：熟悉 Python 后端服务开发，本科。'},headers=CAND).json()
    assert client.get('/fit/benchmark?job_id='+pasted['job_id'],headers=OTHER).status_code==404


def test_vector_batch_keeps_every_resume(client,monkeypatch):
    svc=client.app.state.service;j,_=data(client)
    rows=client.get('/resumes').json()
    svc.settings.vector=True
    calls=[]
    def search(query,owner,env,origin):
        calls.append((owner,env,origin));return [rows[-1]['id']]
    monkeypatch.setattr(svc.retrieval,'search',search)
    result=client.post('/batches/run',json={'job_id':j['id']})
    assert result.status_code==200
    assert {r['resume_id'] for r in result.json()}=={r['id'] for r in rows}
    assert calls==[('enterprise:demo','demo','synthetic')]


def test_imported_pack_version_is_preserved_in_reports(client):
    pack=client.get('/config/packs').json();pack['pack_version']='reviewed-pack-2'
    assert client.post('/config/packs/import',json=pack).status_code==200
    assert client.get('/config/packs/export').json()['pack_version']=='reviewed-pack-2'
    report=client.get('/assessments').json()[0]
    response=client.post('/assessments',json={'job_id':report['job_id'],'resume_ids':[report['resume_id']]})
    assert response.json()['reports'][0]['pack_version']=='reviewed-pack-2'


@pytest.mark.parametrize('name,field,value',[
    ('priorities','enabled',[{}]),('preferences','dimensions',['bad']),
    ('rubric','skill_anchors',{}),('presentation','tier_labels',[]),
    ('presentation','banned_terms',None)])
def test_malformed_config_rejected_without_damage(client,name,field,value):
    before=client.get('/config/'+name).json()
    changed=copy.deepcopy(before);changed['version']='invalid-new';changed[field]=value
    response=client.put('/config/'+name,json=changed)
    assert response.status_code==400
    assert client.get('/config/'+name).json()==before
