import copy
import json
from types import SimpleNamespace
import httpx
import pytest
from app.agents import AgentGateway
from app.errors import DomainError


def gateway(monkeypatch, outputs):
    calls=[]; requests=[]
    settings=SimpleNamespace(api_key='test-only-key',llm_mode='deepseek',base_url='https://example.invalid',model='test',input_price=2,output_price=3)
    class MockClient:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,headers,json):
            requests.append(json)
            content=outputs.pop(0)
            return httpx.Response(200,json={'choices':[{'message':{'content':content}}],'usage':{'prompt_tokens':100,'completion_tokens':20}},request=httpx.Request('POST',url))
    monkeypatch.setattr('app.agents.httpx.Client',MockClient)
    return AgentGateway(settings,lambda row:calls.append(copy.deepcopy(row))),calls,requests


def test_invalid_quote_retries_then_accepts_and_audits(monkeypatch):
    text='岗位要求：熟悉 Python。'
    profile={'direction':'后端开发','education':None,'requirements':[{'skill':'Python','required_level':2,'quote':'凭空引用','hard':True}]}
    good=copy.deepcopy(profile);good['requirements'][0]['quote']='熟悉 Python'
    agent,calls,requests=gateway(monkeypatch,[json.dumps(profile),json.dumps(good)])
    assert agent.jd(text)==good
    assert len(requests)==2 and [r['result'] for r in calls]==['告警','正常']
    assert calls[0]['input_hash']==calls[1]['input_hash']
    assert all('test-only-key' not in str(row) for row in calls)
    assert calls[1]['cost_cny']>0


def test_invalid_json_stops_after_one_retry(monkeypatch):
    agent,calls,requests=gateway(monkeypatch,['not json','{}'])
    with pytest.raises(DomainError) as exc: agent.jd('岗位要求：熟悉 Python。')
    assert exc.value.code=='AGENT_FAILED' and len(requests)==2
    assert all(row['result']=='告警' for row in calls)


def test_fabricated_resume_evidence_is_not_persisted(client,monkeypatch):
    svc=client.app.state.service
    report=client.get('/assessments').json()[0]
    forged={'skills':[],'dimensions':[{'dimension_id':'D3','tier':'B5','evidence':['不存在的项目成果'],'rationale':'虚构','tier_range':[]}]}
    agent,calls,_=gateway(monkeypatch,[json.dumps(forged),json.dumps(forged)])
    svc.gateway=agent
    before=len(client.get('/assessments').json())
    response=client.post('/assessments',json={'job_id':report['job_id'],'resume_ids':[report['resume_id']]})
    assert response.json()['reports']==[] and len(response.json()['errors'])==1
    assert len(client.get('/assessments').json())==before and len(calls)==2
