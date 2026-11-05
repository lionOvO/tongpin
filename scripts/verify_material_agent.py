"""Explicit manual DeepSeek smoke test using synthetic material; prints no credentials."""
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.settings import Settings
from app.agents import AgentGateway
from app.ai_workspace import AIWorkspace, WorkspaceOutput, INSTRUCTIONS
from app.material_agent import run_material_agent
from app.errors import DomainError


def main():
    streaming = '--stream' in sys.argv
    jobs = '--jobs' in sys.argv
    previews = []
    settings = Settings(); records = []; steps = []
    gateway = AgentGateway(settings, records.append)
    profile = gateway.models.resolve('deepseek', require_ready=True)
    if urlsplit(profile.base_url).hostname != 'api.deepseek.com':
        raise RuntimeError('This check requires the official DeepSeek endpoint.')
    text = '专业：软件工程\n技能：Python 与 SQL\n项目：我使用 Python 开发图书借阅服务，负责接口编写和测试。'
    sources, partial = AIWorkspace.sources({'text': text}, {'source_jd': '使用 Python 开发业务接口，编写接口测试，与团队讨论需求。'}, [])
    def budget():
        if sum(r['cost_cny'] for r in records) >= 1:
            raise DomainError('SMOKE_BUDGET', '合成验证已达到预算上限。', 429)
    start = time.monotonic()
    def job_tools(name, args):
        if name == 'search_jobs':
            return {'jobs': [{'ref': 'sample-python-api', 'title': '合成 Python 接口岗位', 'summary': '使用 Python 开发业务接口与测试。'},
                             {'ref': 'sample-python-platform', 'title': '合成 Python 平台岗位', 'summary': 'Python 平台开发与数据处理。'}]}
        return {'status': 'queued', 'processed': 0, 'total': 2, 'notice': '合成验证任务已排队，工作区会自动更新；请立即回复用户，不要等待。'}
    try:
        output = run_material_agent(gateway=gateway, model_id='deepseek', instructions=INSTRUCTIONS,
            value={'action': 'chat' if jobs else 'draft', 'message': '读取我的简历，查询相关 Python 岗位，选择两个并发起契合度后台分析。启动后立即告诉我进度，不要等待完成。' if jobs else '请读取当前简历和所选岗位，定位 Python 项目，只依据原文生成项目段落的表达优化草稿。',
                   'sources': sources, 'partial_materials': partial, 'history': [],
                   'material_state': {'saved_supplement_count': 0, 'all_supplements_user_confirmed': True}},
            schema=WorkspaceOutput, validate=AIWorkspace.validate, guard=lambda: None,
            progress=lambda label, **kw: steps.append(kw['tool']) if kw.get('tool') and kw.get('complete') else None,
            budget=budget, emit=(lambda kind, value: previews.append(len(value)) if kind == 'preview' else None) if streaming else None,
            job_tools=job_tools if jobs else None)
        result = {'status': 'passed', 'findings': len(output['findings']), 'rewrites': len(output['rewrites'])}
        if jobs and not {'search_jobs', 'start_comparison'}.issubset(steps): result['status'] = 'failed'
        if streaming and len(previews) < 2: result['status'] = 'failed'
    except DomainError as error:
        result = {'status': 'failed', 'code': error.code}
    result.update(provider='DeepSeek 官方', model=profile.model, tools=steps, calls=len(records), stream_updates=len(previews),
        seconds=round(time.monotonic()-start, 2), cost_cny=round(sum(r['cost_cny'] for r in records), 6))
    folder = Path(__file__).resolve().parents[1] / 'artifacts' / 'material-agent'; folder.mkdir(parents=True, exist_ok=True)
    (folder / ('deepseek-phase2-stream-smoke.json' if jobs else 'deepseek-stream-smoke.json' if streaming else 'deepseek-smoke.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__': raise SystemExit(main())
