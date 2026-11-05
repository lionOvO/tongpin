"""Explicit live DeepSeek smoke test, with synthetic material only."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.recruiter_assistant import INSTRUCTIONS, RecruiterAnswer, RecruiterAssistant
from app.service import TalentService
from app.settings import Settings
from app.errors import DomainError


def main():
    folder = Path(__file__).resolve().parents[1] / 'artifacts' / 'recruiter-assistant-smoke'
    settings = Settings(data_dir=folder, env='dev', auto_seed=False)
    settings.vector = False
    service = TalentService(settings)
    sources = {
        'resume': '项目：使用 Python 与 FastAPI 开发订单创建接口，负责参数校验和重复提交的幂等处理。',
        'job': '岗位负责订单接口维护和异常排查，使用 Python 与 FastAPI。',
        'business_context': '希望完善订单重复提交处理。',
    }
    try:
        service.budget_check()
        result = service.gateway.call('RecruiterAssistant', INSTRUCTIONS,
            {'action': 'business', 'message': '这段经历与当前业务有哪些可以进一步了解的关联？', 'history': [], 'sources': sources, 'partial_materials': False},
            RecruiterAnswer, lambda answer: RecruiterAssistant.validate(answer, sources),
            timeout=90, max_tokens=3500, prompt_version='recruiter-assistant-v1', model_id='deepseek')
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'deepseek.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'status': 'passed', 'model_id': 'deepseek', 'kind': result['kind'], 'citations': len(result['citations']), 'questions': len(result['questions']), 'synthetic_only': True}, ensure_ascii=False))
    except DomainError as error:
        print(json.dumps({'status': 'failed', 'code': error.code, 'message': error.message, 'synthetic_only': True}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
