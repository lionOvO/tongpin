"""Isolated manual QA only: scripted provider, synthetic account, disposable DB."""
import os
import sys
import json
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(LLM_MODE='demo', DEEPSEEK_API_KEY='', RELAY_API_KEY='', LLM_PROFILES_JSON='[]')
import uvicorn
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.errors import DomainError
from auth_helpers import FakeSMS, sign_in
from test_material_agent import calls, answer, TEXT
from app.deterministic import parse_jd

folder = Path(__file__).resolve().parents[1] / 'artifacts' / 'material-agent' / f'qa-{os.getpid()}'
settings = Settings(data_dir=folder, env='dev', auto_seed=False)
settings.vector = False; settings.llm_mode = 'deepseek'; settings.api_key = 'synthetic-only'
settings.default_model_id = 'deepseek'; settings.model_profiles_json = '[]'
app = create_app(settings); app.state.auth.sms = FakeSMS()
with TestClient(app) as client:
    user = sign_in(client, '13800000981')
    resume = client.post('/resumes', json={'name': '合成示例 · 后端开发', 'text': TEXT, 'data_origin': 'synthetic'}).json()
    client.post('/ai/workspaces', json={'resume_id': resume['id'], 'jd': '岗位职责：使用 Python 设计业务接口，编写测试，并与团队讨论需求。', 'title': '合成后端岗位'})
    for title in ['合成 Python 接口开发', '合成 Python 平台开发']:
        text = '岗位要求：本科，使用 Python 开发业务接口，编写测试并参与业务项目。'
        app.state.service.db.insert('job_profiles', dict(title=title, source_jd=text, profile=parse_jd(text),
            status='已确认', version=1, published=False), user['actor'])


def provider(messages, tools, **kwargs):
    context = json.loads(messages[1]['content'])
    time.sleep(1.1)
    if '失败测试' in context['message']:
        raise DomainError('AI_TOOL_PROVIDER_FAILED', '合成服务失败，请重试；原材料未改变。', 502)
    names = [m['function']['name'] for msg in messages for m in msg.get('tool_calls', [])]
    if '查询' in context['message'] or '找' in context['message'] or '讨论' in context['message']:
        if not names: return calls(('read_resume', {}), ('search_jobs', {'query': 'Python'}))
        if 'start_comparison' not in names:
            rows = next(json.loads(m['content'])['jobs'] for m in messages if m['role'] == 'tool' and 'jobs' in json.loads(m['content']))
            return calls(('start_comparison', {'job_refs': [r['ref'] for r in rows]}))
        result = {'role': 'assistant', 'content': json.dumps({'reply': '已为你发起多岗位对照，后台会按已保存简历的现有证据分析，结果卡将自动更新。', 'findings': [], 'questions': [], 'rewrites': []}, ensure_ascii=False)}
        return stream(result, kwargs)
    if not names: return calls(('read_resume', {}), ('read_job', {}))
    if 'find_experience' not in names: return calls(('find_experience', {'query': 'Python'}))
    if 'prepare_draft' not in names: return calls(('prepare_draft', {'source_ids': ['R3', 'R2']}))
    result = answer(rewrites=True); obj = json.loads(result['content'])
    rows = [s for m in messages if m['role'] == 'tool' for s in json.loads(m['content']).get('sources', [])]
    source = next(s for s in rows if s['id'] == 'R3')
    obj['rewrites'][0]['before'] = source['text']; obj['rewrites'][0]['citations'][0]['quote'] = source['text']
    second = next(s for s in rows if s['id'] == 'R2')
    obj['rewrites'].append({'source_id': 'R2', 'before': second['text'], 'after': '技能：SQL、Python', 'reason': '调整技能展示顺序。', 'citations': [{'source_id': 'R2', 'quote': second['text']}]})
    result['content'] = json.dumps(obj, ensure_ascii=False)
    return stream(result, kwargs)


def stream(result, kwargs):
    if kwargs.get('on_delta'):
        text = result['content']
        for i in range(0, len(text), 5):
            kwargs['on_delta'](text[i:i+5]); time.sleep(.025)
    return result


def evaluate(job, resume, actor):
    time.sleep(2)
    return {'dimensions': [{'dimension_id': 'D3', 'name': '项目经验', 'tier': 'B4' if '接口' in job['title'] else 'B3', 'evidence': ['合成项目']}],
        'skill_levels': [], 'sort_key': {}, 'assessed_at': '2026-10-27T00:00:00Z'}


app.state.service.gateway.tool_step = provider
app.state.service.evaluate = evaluate
if __name__ == '__main__': uvicorn.run(app, host='127.0.0.1', port=8027)
