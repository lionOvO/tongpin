"""Manual smoke test using synthetic material only; never included in pytest."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.recruiter_review import INSTRUCTIONS, ReviewOutput, RecruiterReview
from app.service import TalentService
from app.settings import Settings
from app.errors import DomainError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default=None)
    args = parser.parse_args()
    folder = Path(__file__).resolve().parents[1] / 'artifacts' / 'recruiter-model-smoke'
    settings = Settings(data_dir=folder, env='dev', auto_seed=False)
    settings.vector = False
    svc = TalentService(settings)
    sources = {
        'resume': '求职方向：后端开发。\n项目：使用 Python 和 FastAPI 开发订单创建与查询接口，增加重复提交的幂等校验。\n项目：根据慢查询日志调整 MySQL 联合索引，使用 EXPLAIN 核对查询计划。\n项目：使用任务队列发送订单通知，增加失败重试和人工补发。',
        'job': '岗位负责订单服务和消息通知，使用 Python、FastAPI、MySQL，维护接口并排查数据查询性能问题。',
        'business_context': '公司需要完善订单创建流程，减少重复订单，并维护运营查询接口。',
    }
    try:
        profile = svc.models.resolve(args.model, require_ready=True)
        result = svc.gateway.call('RecruiterCard', INSTRUCTIONS, {'sources': sources, 'partial_materials': False},
            ReviewOutput, lambda obj: RecruiterReview.validate(obj, sources),
            timeout=60, max_tokens=4500, prompt_version='recruiter-card-v1', model_id=profile.id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (profile.id + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'status': 'passed', 'model': profile.model, 'strengths': len(result['strengths']),
            'business_links': sum(bool(s['business_link']) for s in result['strengths']),
            'interview_questions': len(result['strengths']) + len(result['open_questions']), 'synthetic_only': True}, ensure_ascii=False))
    except DomainError as exc:
        print(json.dumps({'status': 'failed', 'code': exc.code, 'message': exc.message}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
