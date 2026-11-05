"""Manual UI QA: isolated synthetic accounts and validated model fixtures.

Never imported by runtime or pytest; no production accounts or external requests.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.recruiter_review import ReviewOutput
from auth_helpers import FakeSMS, sign_in
from test_hiring import apply_body, change
from uuid import uuid4
from scripts.manage_accounts import promote

ROOT = Path(__file__).resolve().parents[1]
settings = Settings(data_dir=ROOT / 'artifacts' / 'recruiter-browser-qa' / str(os.getpid()), env='dev', auto_seed=False)
settings.vector = False; settings.llm_mode = 'demo'; settings.api_key = ''; settings.relay_api_key = ''
app = create_app(settings); app.state.auth.sms = FakeSMS()
resume_text = '求职方向：后端开发。\n项目：使用 Python 和 FastAPI 开发订单创建与查询接口，增加重复提交的幂等校验。\n项目：根据慢查询日志调整 MySQL 联合索引，使用 EXPLAIN 核对查询计划。\n项目：使用任务队列发送订单通知，增加失败重试和人工补发。'
jd = '岗位负责订单服务和消息通知，使用 Python、FastAPI、MySQL，维护接口并排查数据查询性能问题。'
context = '公司需要完善订单创建流程，减少重复订单，并维护运营查询接口。'


def gateway(agent, instructions, value, schema, validate=None, **kwargs):
    fixture = ROOT / 'artifacts' / 'recruiter-model-smoke' / 'deepseek.json'
    if agent == 'RecruiterAssistant':
        quote = value['sources']['resume'].split('\n')[1] if '\n' in value['sources']['resume'] else value['sources']['resume']
        output = {'kind': 'answer', 'reply': '简历记录了这段具体项目经历：' + quote + '\n\n可以围绕实际负责的任务、实现过程和验证方法进一步沟通。企业业务需求需要与本人确认，不能直接作为其已有经历。',
            'citations': [{'source': 'resume', 'quote': quote}], 'questions': ['请介绍这段经历中实际负责的工作，以及如何核对实现结果。']}
    elif value['sources']['resume'] == resume_text and fixture.exists():
        output = json.loads(fixture.read_text(encoding='utf-8'))
    else:
        quote = value['sources']['resume'].split('\n')[0]
        output = {'overview': '', 'overview_quotes': [], 'strengths': [{
            'title': '项目实践', 'work': quote, 'evidence_kind': 'experience', 'resume_quote': quote,
            'business_link': None, 'interview_question': '请介绍这段经历中具体负责的工作与实现过程。'}], 'open_questions': []}
    result = schema.model_validate(output).model_dump()
    if validate: validate(result)
    return result


with TestClient(app) as company, TestClient(app) as candidate:
    sign_in(company, '13800000991', 'enterprise')
    job = company.post('/jobs', json={'title': '后端开发工程师 · 合成测试', 'jd': jd, 'data_origin': 'synthetic'}).json()
    job = company.put('/jobs/' + job['id'] + '/confirm', json={'profile': job['profile'], 'expected_version': job['version']}).json()
    company.put('/jobs/' + job['id'] + '/visibility', json={'published': True})
    applications = []
    for index, (name, text) in enumerate([
        ('陈予安 · 合成示例', resume_text),
        ('林知夏 · 合成示例', '项目：使用 Vue 3 实现运营后台的组合筛选和分页，负责图表与明细联动。\n项目：为商品列表增加虚拟滚动和图片懒加载。'),
        ('周启明 · 合成示例', '项目：编写 SQL 汇总渠道访问与成交数据，与业务同事核对去重口径。\n项目：使用 Python 清洗供应商数据，生成异常记录清单。'),
    ]):
        candidate.cookies.clear(); sign_in(candidate, '1380000098' + str(index))
        resume = candidate.post('/resumes', json={'name': name, 'text': text, 'data_origin': 'synthetic'}).json()
        row = candidate.post('/applications', json=apply_body(job, resume)).json()
        applications.append(row)
        if index == 0: first = row
    imported = company.post('/applications/' + first['id'] + '/resume-import', json={'expected_version':first['version']}).json()['resume']
    assert 'id' in imported, imported
    result = company.post('/assessments', json={'job_id':job['id'], 'resume_ids':[imported['id']]})
    assert result.status_code == 200, result.text
    with TestClient(app) as unverified, TestClient(app) as admin:
        sign_in(unverified, '13800000994')
        sign_in(admin, '13800000993', 'enterprise')
        promote(app.state.auth, '13800000993')
    settings.llm_mode = 'live'; settings.api_key = 'ui-fixture-no-network'
    app.state.service.gateway.call = gateway
    response = company.post('/applications/' + first['id'] + '/recruiter-review', json={'expected_version': 1, 'business_context': context})
    assert response.status_code == 200, response.text

    # Human messaging fixtures: accepted thread + outstanding invitation. Synthetic data only.
    candidate.cookies.clear(); sign_in(candidate, '13800000980')
    row = change(company,first,'invite','你好，我们想进一步了解你在订单接口和查询优化中的工作，欢迎聊聊具体职责与双方期待。').json()
    row = change(candidate,row,'accept').json()
    for sender, text in [
        (company,'你好，感谢接受邀请。这个岗位主要维护订单服务和运营查询接口，可以先介绍你负责的部分吗？'),
        (candidate,'你好。我负责订单创建与查询接口，包括参数校验、幂等处理和接口测试，也参与了慢查询排查。'),
        (company,'收到。方便介绍一个慢查询排查的具体例子吗？例如怎样定位、如何调整索引以及怎样验证结果。'),
        (candidate,'可以。我先对照慢查询日志检查查询条件，再用 EXPLAIN 核对执行计划，针对常用筛选调整联合索引。'),
        (company,'这与我们当前的运营查询工作很接近。接下来可以聊聊协作方式、职责范围和你对岗位的期待。'),
    ]:
        response = sender.post('/applications/' + row['id'] + '/messages',json={'text':text,'expected_version':row['version'],'request_id':str(uuid4())})
        assert response.status_code == 200, response.text
        row = response.json()
    response = change(company,applications[1],'invite','你好，我们正在完善运营后台，希望了解你的 Vue 页面与图表联动经历。你愿意进一步沟通吗？')
    assert response.status_code == 200, response.text

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8019)
