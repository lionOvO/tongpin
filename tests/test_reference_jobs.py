"""Private candidate reference jobs: authenticated writes and shared comparison path."""
import pytest
from test_hiring import scene
from test_job_fit import finished
from app.errors import DomainError

BODY = {'title': '合成 Agent 开发工程师', 'jd': '岗位职责：使用 Python 开发业务接口。任职要求：熟悉 FastAPI 和 Docker，参与业务系统项目交付。', 'data_origin': 'synthetic'}


def test_reference_permissions_and_trimmed_validation(scene):
    app, a, b, c, d, guest, *_ = scene
    assert guest.post('/jobs/references', json=BODY).status_code == 401
    assert a.post('/jobs/references', json=BODY).status_code == 403
    assert c.post('/jobs/references', json=BODY, headers={'X-CSRF-Token':'wrong'}).status_code == 403
    for patch in [{'title':'  '}, {'jd':' '*30}, {'jd':'过短描述'}, {'data_origin':'other'}]:
        assert c.post('/jobs/references', json={**BODY, **patch}).status_code == 422
    assert not [j for j in app.state.service.db.list('job_profiles') if j.get('reference_fingerprint')]


def test_reference_persists_privately_reuses_duplicates_and_compares_with_public_job(scene, monkeypatch):
    app, a, b, c, d, guest, users, public, resume = scene
    calls=[]; original=app.state.service.gateway.jd
    def jd(text, **kwargs):
        calls.append(kwargs)
        return original(text, **kwargs)
    monkeypatch.setattr(app.state.service.gateway, 'jd', jd)
    created=c.post('/jobs/references', json={**BODY, 'title':' '+BODY['title']+' '})
    assert created.status_code == 200, created.text
    job=created.json()
    assert job['title']==BODY['title'] and job['personal_reference'] and not job['published']
    assert job['source_jd']==BODY['jd'] and not job['accepts_applications']
    assert job['status']=='已确认' and calls==[{'model_id':'deepseek'}]
    assert c.post('/jobs/references', json=BODY).json()['id']==job['id']
    assert len(calls)==1
    assert job['id'] in [j['id'] for j in c.get('/jobs').json()]
    for other in [a,b,d]:
        assert job['id'] not in [j['id'] for j in other.get('/jobs').json()]
    assert c.put('/jobs/'+job['id']+'/visibility',json={'published':True}).status_code==403
    task=c.post('/compare/tasks',json={'resume_id':resume['id'],'job_ids':[public['id'],job['id']],'request_id':'private-reference-comparison'})
    assert task.status_code==202,task.text
    result=finished(c,task.json()['id'])
    assert result['status']=='completed',result
    assert {r['job_id'] for r in result['ranked_results']}=={public['id'],job['id']}
    assert next(r for r in result['ranked_results'] if r['job_id']==job['id'])['personal_reference']


def test_reference_parse_failure_leaves_no_partial_job_and_allows_retry(scene,monkeypatch):
    app, a, b, c, *_ = scene
    original=app.state.service.gateway.jd
    def fail(*args,**kwargs): raise DomainError('AGENT_FAILED','测试解析失败',502)
    monkeypatch.setattr(app.state.service.gateway,'jd',fail)
    assert c.post('/jobs/references',json=BODY).status_code==502
    assert not [j for j in app.state.service.db.list('job_profiles') if j.get('reference_fingerprint')]
    monkeypatch.setattr(app.state.service.gateway,'jd',original)
    assert c.post('/jobs/references',json=BODY).status_code==200
