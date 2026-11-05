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
    monkeypatch.setattr('app.agents.ModelClient',MockClient)
    return AgentGateway(settings,lambda row:calls.append(copy.deepcopy(row))),calls,requests


def test_invalid_quote_retries_then_accepts_and_audits(monkeypatch):
    text='岗位要求：熟悉 Python。'
    profile={'direction':'后端开发','education':None,'requirements':[{'skill':'Python','required_level':2,'quote':'凭空引用','hard':True}]}
    good=copy.deepcopy(profile);good['requirements'][0]['quote']='熟悉 Python'
    agent,calls,requests=gateway(monkeypatch,[json.dumps(profile),json.dumps(good)])
    assert agent.jd(text)==good
    assert len(requests)==2 and [r['result'] for r in calls]==['告警','正常']
    assert calls[0]['input_hash']==calls[1]['input_hash']
    assert '未通过结构或证据校验' in requests[1]['messages'][0]['content']
    assert all('test-only-key' not in str(row) for row in calls)
    assert calls[1]['cost_cny']>0
    assert calls[0]['failure_code']=='EVIDENCE_INVALID'
    assert calls[0]['failure_stage']=='evidence_validation'
    assert '逐字复制' in requests[1]['messages'][0]['content']
    assert 'failure_code' not in calls[1]


def test_report_evaluation_defaults_to_deepseek_even_when_catalog_default_is_relay(monkeypatch):
    agent, _, _ = gateway(monkeypatch, [])
    agent.models.settings.default_model_id = 'relay-gpt-61'
    selected = []
    def model_call(*args, **kwargs):
        selected.append(kwargs['model_id'])
        return {'skills': [], 'dimensions': []}
    monkeypatch.setattr(agent, 'call', model_call)
    result = agent.evaluate('使用 Python 开发接口并进行测试。', {'requirements': []}, {}, [])
    assert selected == ['deepseek'] and result == {'skills': [], 'dimensions': []}


def test_invalid_json_stops_after_one_retry(monkeypatch):
    agent,calls,requests=gateway(monkeypatch,['not json','{}'])
    with pytest.raises(DomainError) as exc: agent.jd('岗位要求：熟悉 Python。')
    assert exc.value.code=='AGENT_FAILED' and len(requests)==2
    assert all(row['result']=='告警' for row in calls)
    assert all(row['failure_code']=='AI_SCHEMA_INVALID' for row in calls)


def test_markdown_quotes_retry_with_original_and_behavior_limits(monkeypatch):
    from app.deterministic import rating_config
    text='专业：软件工程，本科\n**课程项目**：使用 Python 实现数据统计'
    quote='**课程项目**：使用 Python 实现数据统计'
    good={'dimensions':[{'dimension_id':'D3','tier':'B4','evidence':[quote],
                         'rationale':'简历描述相关课程项目','anchor_hits':['参与相关项目']}],
          'skills':[{'skill':'Python','evidence_level':2,'evidence':[quote],
                     'anchor_hits':[{'feature':'任务与对象','quote':quote}]}]}
    bad=copy.deepcopy(good)
    bad['dimensions'][0]['evidence']=['课程项目：使用 Python 实现数据统计']
    agent,calls,requests=gateway(monkeypatch,[json.dumps(bad),json.dumps(good)])
    profile={'direction':'后端开发','education':'本科','requirements':[{'skill':'Python','required_level':3,'quote':'熟练 Python','hard':True}]}
    result=agent.evaluate(text,profile,rating_config(),[])
    assert result['dimensions'][0]['evidence']==[quote]
    assert result['skills'][0]['evidence']==[quote]
    supplied=json.loads(requests[0]['messages'][1]['content'])
    assert supplied['skill_evidence_limits']==[{'skill':'Python','max_level':2,'evidence':[quote]}]
    assert calls[0]['failure_code']=='EVIDENCE_INVALID' and calls[1]['result']=='正常'
    assert '保留 Markdown' in requests[1]['messages'][0]['content']


def test_failed_evidence_returns_specific_message_without_private_details(monkeypatch):
    agent,calls,_=gateway(monkeypatch,[json.dumps({'direction':'后端开发','requirements':[{'skill':'Python','required_level':2,'quote':'private-source-fragment'}]} )]*2)
    with pytest.raises(DomainError) as exc:agent.jd('岗位要求：熟悉 Python。')
    assert exc.value.code=='AGENT_FAILED' and '原始材料' in exc.value.message
    assert 'private-source-fragment' not in str(calls) and 'private-source-fragment' not in exc.value.message


def test_evaluation_schema_only_exposes_model_owned_dimensions():
    from app.agents import AnchoredTierEvidence
    from pydantic import ValidationError
    assert AnchoredTierEvidence.model_json_schema()['properties']['dimension_id']['enum']==['D1','D3','D5']
    for name in ['D2','D4']:
        with pytest.raises(ValidationError):
            AnchoredTierEvidence.model_validate({'dimension_id':name,'tier':'insufficient','evidence':[],'rationale':'无证据'})


def test_workspace_retry_corrects_action_without_exposing_error_details(monkeypatch):
    from app.ai_workspace import WorkspaceOutput
    output=json.dumps({'reply':'请核对项目职责','findings':[],'questions':[],'rewrites':[]})
    agent,calls,requests=gateway(monkeypatch,[output,output])
    attempts=[]
    def validate(result):
        attempts.append(result)
        if len(attempts)==1:
            raise DomainError('AI_DRAFT_SCOPE','private-provider-detail',422)
    agent.call('CandidateWorkspace','按当前操作返回',{'action':'analyze'},WorkspaceOutput,validate)
    correction=requests[1]['messages'][0]['content']
    assert 'rewrites 必须为 []' in correction
    assert 'private-provider-detail' not in correction
    assert requests[0]['messages'][1]==requests[1]['messages'][1]
    assert len(calls)==2


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


@pytest.mark.parametrize('interval', [['B3'], ['B3','B3']])
def test_single_tier_arrays_are_canonical_without_changing_evidence(monkeypatch, interval):
    text = '合成项目：使用 Python 实现数据统计'
    result = {'dimensions':[{'dimension_id':'D3','tier':'B3','tier_range':interval,
        'evidence':[text],'rationale':'项目描述','anchor_hits':['相关项目']}], 'skills':[]}
    agent,calls,requests = gateway(monkeypatch,[json.dumps(result)])
    output = agent.evaluate(text,{'requirements':[]},{},[])
    assert output['dimensions'][0]['tier'] == 'B3'
    assert output['dimensions'][0]['tier_range'] == []
    assert output['dimensions'][0]['evidence'] == [text]
    assert len(calls) == 1 and calls[0]['result'] == '正常'


@pytest.mark.parametrize('tier,interval,reason,code', [
    ('B3',['B2'],'','INTERVAL_INVALID'),
    ('B3',['B1','B3'],'跨档描述','INTERVAL_INVALID'),
    ('B3',['B3','B4'],'','CROSS_BAND_REASON_REQUIRED'),
    ('insufficient',['B3','B4'],'跨档描述','INTERVAL_INVALID'),
])
def test_real_invalid_intervals_still_fail_after_retry(monkeypatch,tier,interval,reason,code):
    text = '合成项目经历'
    value = {'dimensions':[{'dimension_id':'D3','tier':tier,'tier_range':interval,
        'cross_band_reason':reason,'evidence':[text],'rationale':'项目描述','anchor_hits':['相关项目']}],'skills':[]}
    agent,calls,_ = gateway(monkeypatch,[json.dumps(value)]*2)
    with pytest.raises(DomainError) as exc:
        agent.evaluate(text,{'requirements':[]},{},[])
    assert [row['failure_code'] for row in calls] == [code,code]
    assert '档位区间' in exc.value.message
