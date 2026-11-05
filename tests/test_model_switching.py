"""Provider routing and per-task switching without network or real credentials."""
import json
import time
from types import SimpleNamespace
import httpx
import pytest
from app.agents import AgentGateway
from app.ai_workspace import WorkspaceOutput
from app.model_catalog import ModelCatalog
from app.model_transport import parse_responses, stream_response, raise_provider_status
from app.errors import DomainError
from test_ai_workspace import setup, mock_provider, turn, PATH


def settings(**values):
    return SimpleNamespace(api_key='test-deepseek-secret',llm_mode='live',base_url='https://deepseek.invalid',model='deepseek-flash',
        input_price=2,output_price=3,relay_api_key='test-relay-secret',relay_base_url='https://relay.invalid',
        relay_model='gpt-5.6-sol',relay_sol_model='gpt-6.1-sol',relay_input_price=10,relay_output_price=20,**values)


def response(content=None,**extra):
    return {'status':'completed','output':[{'type':'reasoning','summary':[]},{'type':'message','role':'assistant','status':'completed',
        'content':[{'type':'output_text','text':content or json.dumps({'reply':'材料检查完成','findings':[],'questions':[],'rewrites':[]})}]}],
        'usage':{'input_tokens':100,'output_tokens':20},**extra}


def test_relay_uses_stream_by_default_but_allows_explicit_override(monkeypatch):
    from app.settings import Settings
    monkeypatch.delenv('RELAY_RESPONSES_STREAM')
    assert ModelCatalog(Settings()).resolve('relay-gpt-61').stream is True
    monkeypatch.setenv('RELAY_RESPONSES_STREAM','false')
    assert ModelCatalog(Settings()).resolve('relay-gpt-61').stream is False


def test_responses_route_parameters_parse_and_cost_without_secret_audit(monkeypatch):
    requests=[];audit=[]
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,headers,json):
            requests.append((url,headers,json))
            return httpx.Response(200,json=response(),request=httpx.Request('POST',url))
    monkeypatch.setattr('app.agents.ModelClient',Client)
    agent=AgentGateway(settings(),audit.append)
    out=agent.call('CandidateWorkspace','只返回 JSON',{'action':'chat'},WorkspaceOutput,model_id='relay-gpt',max_tokens=4500)
    url,headers,payload=requests[0]
    assert url=='https://relay.invalid/v1/responses' and headers['Authorization']=='Bearer test-relay-secret'
    assert payload['model']=='gpt-5.6-sol' and payload['store'] is False
    assert payload['text']=={'format':{'type':'json_object'}} and payload['max_output_tokens']==4500
    assert 'JSON' in payload['input'][0]['content'][0]['text']
    assert all(k not in payload for k in ('temperature','thinking','response_format','tools','previous_response_id'))
    assert out['reply']=='材料检查完成'
    assert audit[0]['usage']=={'prompt_tokens':100,'completion_tokens':20}
    assert audit[0]['cost_cny']==0.0014 and audit[0]['protocol']=='responses'
    assert 'secret' not in str(audit) and '材料检查完成' not in str(audit)


def test_retries_stay_on_selected_provider_and_model(monkeypatch):
    requests=[];audit=[]
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,headers,json):
            requests.append((url,headers,json))
            return httpx.Response(401,json={'error':'not allowed'},request=httpx.Request('POST',url))
    monkeypatch.setattr('app.agents.ModelClient',Client)
    with pytest.raises(DomainError) as error:
        AgentGateway(settings(),audit.append).call('CandidateWorkspace','JSON',{},WorkspaceOutput,model_id='relay-gpt-61')
    assert error.value.code=='AGENT_FAILED'
    assert len(requests)==2 and {r[2]['model'] for r in requests}=={'gpt-6.1-sol'}
    assert all(r[1]['Authorization']=='Bearer test-relay-secret' for r in requests)


def test_stream_required_is_diagnosed_without_leaking_provider_body(monkeypatch):
    requests=[];audit=[]
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,headers,json):
            requests.append(json)
            return httpx.Response(400,json={'error':{'code':'stream_required','message':'test-relay-secret private-resume'}},request=httpx.Request('POST',url))
    monkeypatch.setattr('app.agents.ModelClient',Client)
    with pytest.raises(DomainError) as error:
        AgentGateway(settings(),audit.append).call('CandidateWorkspace','JSON',{},WorkspaceOutput,model_id='relay-gpt-61')
    assert '流式请求' in error.value.message and '校验' not in error.value.message
    assert len(requests)==2 and requests[0]['instructions']==requests[1]['instructions']
    assert all(row['provider_error_code']=='stream_required' and row['provider_status']==400 for row in audit)
    assert 'private-resume' not in str(audit)+error.value.message
    assert 'test-relay-secret' not in str(audit)+error.value.message


def test_provider_timeout_is_distinct_and_audited_without_private_input(monkeypatch):
    audit = []; requests = []
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            requests.append(url)
            raise httpx.ReadTimeout('private-resume test-relay-secret')
    monkeypatch.setattr('app.agents.ModelClient', Client)
    with pytest.raises(DomainError) as error:
        AgentGateway(settings(), audit.append).call('RecruiterCard', 'JSON', {'synthetic': True}, WorkspaceOutput)
    assert error.value.code == 'AI_PROVIDER_TIMEOUT' and '响应超时' in error.value.message
    assert len(requests) == 2 and all(row['provider_error_code'] == 'timeout' for row in audit)
    assert 'private-resume' not in str(audit) + error.value.message
    assert 'test-relay-secret' not in str(audit) + error.value.message


@pytest.mark.parametrize('status,expected',[(400,'接入参数'),(401,'密钥'),(403,'权限'),(429,'额度'),(503,'响应异常')])
def test_provider_status_has_actionable_safe_message(monkeypatch,status,expected):
    audit=[]
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,**kwargs):
            return httpx.Response(status,json={'error':{'code':'private-resume','message':'test-relay-secret'}},request=httpx.Request('POST',url))
    monkeypatch.setattr('app.agents.ModelClient',Client)
    with pytest.raises(DomainError) as error:
        AgentGateway(settings(),audit.append).call('CandidateWorkspace','JSON',{},WorkspaceOutput,model_id='relay-gpt-61')
    assert expected in error.value.message
    assert all('provider_error_code' not in row for row in audit)
    assert 'private-resume' not in str(audit)+error.value.message and 'test-relay-secret' not in str(audit)+error.value.message


def test_streaming_http_error_body_is_bounded_and_recognized():
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(400,json={'error':{'code':'stream_required','message':'private-input'}}))) as client:
        with client.stream('POST','https://relay.invalid/v1/responses') as response:
            with pytest.raises(httpx.HTTPStatusError) as error:
                raise_provider_status(response,streaming=True)
    assert error.value.provider_code=='stream_required'

    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(400,content=b'x'*20000))) as client:
        with client.stream('POST','https://relay.invalid/v1/responses') as response:
            with pytest.raises(httpx.HTTPStatusError) as error:
                raise_provider_status(response,streaming=True)
    assert not hasattr(error.value,'provider_code')


@pytest.mark.parametrize('obj',[
    response(status='incomplete'),response(error={'message':'provider detail'}),response(incomplete_details={'reason':'max_output_tokens'}),
    response(output=[{'type':'function_call','name':'read_database'}]),
    response(output=[{'type':'message','role':'assistant','content':[{'type':'refusal','refusal':'no'}]}]),
    response(output=[]),
])
def test_responses_incomplete_refusal_and_tools_never_accepted(obj):
    with pytest.raises(ValueError): parse_responses(obj)


def test_sse_requires_completed_event_and_normalizes_final_response():
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def raise_for_status(self): pass
        def iter_lines(self):
            yield 'event: response.output_text.delta';yield 'data: '+json.dumps({'type':'response.output_text.delta','delta':'ignored'})
            yield '';yield 'data: '+json.dumps({'type':'response.completed','response':response()});yield ''
    class Client:
        def stream(self,*args,**kwargs): return Response()
    obj=stream_response(Client(),'https://relay.invalid/v1/responses',{}, {})
    assert parse_responses(obj)[1]['prompt_tokens']==100


def test_model_catalog_masks_secrets_and_rejects_client_urls():
    catalog=ModelCatalog(settings())
    assert 'secret' not in str(catalog.public())
    assert 'relay.invalid' not in str(catalog.public())
    assert 'secret' not in repr(catalog.resolve('relay-gpt'))
    with pytest.raises(DomainError): catalog.resolve('https://attacker.invalid')
    for item in [{'id':'deepseek'}, {'id':'new','label':'New','provider':'Other','model':'model','protocol':'responses','base_url':'http://localhost:8000','api_key_env':'OTHER_KEY'}]:
        with pytest.raises(ValueError): ModelCatalog(settings(model_profiles_json=json.dumps([item])))


def test_switch_is_per_task_preserves_evidence_and_records_provenance(setup,monkeypatch):
    app,first,second,_,_,resume,session=setup
    app.state.service.settings.relay_api_key='test-relay-secret'
    mock_provider(app,monkeypatch)
    session=turn(first,session,'draft').json()
    before=session['analysis'];draft=session['drafts'][-1]
    other=first.post(PATH,json={'resume_id':resume['id']}).json()
    request={'model_id':'relay-gpt','expected_version':session['version']}
    switched=first.post(f"{PATH}/{session['id']}/model",json=request)
    assert switched.status_code==200,switched.text
    row=switched.json()
    assert row['model_id']=='relay-gpt' and row['version']==session['version']+1
    assert row['analysis']==before and row['drafts'][-1]==draft
    assert first.get(f"{PATH}/{other['id']}").json()['model_id']=='deepseek'
    assert second.post(f"{PATH}/{session['id']}/model",json=request).status_code==404
    assert first.post(f"{PATH}/{session['id']}/model",json=request).status_code==409
    after=turn(first,row,'analyze').json()
    assert after['messages'][-1]['model']=='gpt-5.6-sol' and after['analysis']['provider']=='SourcesData 中转站'
    assert after['drafts'][-1]['model_id']=='deepseek'
    assert app.state.service.settings.model=='deepseek-flash'


def test_switch_denies_missing_key_busy_extra_arguments_and_wrong_scope(setup):
    app,first,_,_,_,_,session=setup
    endpoint=f"{PATH}/{session['id']}/model"
    assert first.post(endpoint,json={'model_id':'relay-gpt','expected_version':1}).status_code==503
    assert first.post(endpoint,json={'model_id':'unknown','expected_version':1}).status_code==422
    assert first.post(endpoint,json={'model_id':'deepseek','expected_version':1,'base_url':'https://attacker.invalid'}).status_code==422
    assert first.get('/ai/models',headers={'X-Session-Scope':'admin'}).status_code==403
    assert first.post(endpoint,json={'model_id':'deepseek-pro','expected_version':1},headers={'X-CSRF-Token':'wrong'}).status_code==403
    app.state.service.db.update('ai_sessions',session['id'],{'running':'test','running_until':time.time()+30})
    assert first.post(endpoint,json={'model_id':'deepseek-pro','expected_version':1}).status_code==409


def test_legacy_and_removed_model_tasks_remain_readable_and_can_switch(setup):
    app,first,_,_,_,_,session=setup
    db=app.state.service.db
    db.update('ai_sessions',session['id'],{'model_id':'removed-provider','model_selection':{'model':'old-model','provider':'Old'}})
    old=first.get(f"{PATH}/{session['id']}").json()
    assert old['model_ready'] is False and old['messages']==[]
    result=first.post(f"{PATH}/{session['id']}/model",json={'model_id':'deepseek','expected_version':old['version']})
    assert result.status_code==200 and result.json()['model_ready'] is True
