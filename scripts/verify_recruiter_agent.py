"""Explicit official DeepSeek smoke; fixed synthetic materials, bounded cost."""
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agents import AgentGateway
from app.settings import Settings
from app.recruiter_agent import run_recruiter_agent
from app.recruiter_assistant import INSTRUCTIONS, RecruiterAnswer, RecruiterAssistant
from app.errors import DomainError


def main():
    settings = Settings(); records = []; steps = []; previews = []
    gateway = AgentGateway(settings, records.append)
    profile = gateway.models.resolve('deepseek', require_ready=True)
    if urlsplit(profile.base_url).hostname != 'api.deepseek.com':
        raise RuntimeError('Official DeepSeek endpoint required.')
    sources = {'resume': '项目：使用 Python 与 FastAPI 开发订单创建接口，负责参数校验和重复提交的幂等处理。',
        'job': '岗位负责订单接口维护和异常排查，使用 Python 与 FastAPI。',
        'business_context': '希望完善订单重复提交处理。'}
    def budget():
        if sum(r['cost_cny'] for r in records) >= 1: raise DomainError('SMOKE_BUDGET', '合成验证达到预算上限。', 429)
    start = time.monotonic()
    try:
        output = run_recruiter_agent(gateway=gateway, instructions=INSTRUCTIONS,
            value={'action': 'interview', 'message': '读取当前授权简历、岗位和企业背景，定位相关经历，准备两条有依据的面试追问建议。不要保存提纲。',
                'sources': sources, 'history': [], 'partial_materials': False},
            schema=RecruiterAnswer, validate=RecruiterAssistant.validate, guard=lambda: None, budget=budget,
            progress=lambda label, **kw: steps.append(kw['tool']) if kw.get('complete') else None,
            emit=lambda kind, text: previews.append(len(text)) if kind == 'preview' else None)
        passed = len(previews) > 1 and bool(output['questions']) and {'read_application', 'read_job_requirements', 'read_business_context', 'prepare_interview_outline'}.issubset(steps)
        result = {'status': 'passed' if passed else 'failed', 'questions': len(output['questions']), 'citations': len(output['citations'])}
    except DomainError as e: result = {'status': 'failed', 'code': e.code}
    result.update(synthetic_only=True, provider='DeepSeek 官方', model=profile.model, tools=steps,
        calls=len(records), stream_updates=len(previews), seconds=round(time.monotonic()-start, 2),
        cost_cny=round(sum(r['cost_cny'] for r in records), 6))
    folder = Path(__file__).resolve().parents[1] / 'artifacts' / 'recruiter-agent-phase3'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'deepseek-smoke.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__': raise SystemExit(main())
