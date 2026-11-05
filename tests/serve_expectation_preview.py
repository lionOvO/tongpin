"""Isolated UI QA for expectation visibility. Fake SMS, synthetic data, no model calls."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from auth_helpers import FakeSMS, sign_in

settings = Settings(data_dir=ROOT / 'artifacts' / 'expectation-preview' / str(os.getpid()), env='dev', auto_seed=False)
settings.vector = False; settings.llm_mode = 'demo'; settings.api_key = ''; settings.relay_api_key = ''
app = create_app(settings); app.state.auth.sms = FakeSMS()
with TestClient(app) as enterprise, TestClient(app) as candidate:
    sign_in(enterprise, '13800000991', 'enterprise'); sign_in(candidate, '13800000980')
    job = enterprise.post('/jobs', json={'title': '公开设置验证岗位 · 合成', 'jd': '岗位要求：本科，熟悉 Python 与 FastAPI，负责后端接口开发和项目维护。', 'data_origin': 'synthetic'}).json()
    job = enterprise.put('/jobs/' + job['id'] + '/confirm', json={'profile': job['profile'], 'expected_version': job['version']}).json()
    assert enterprise.put('/jobs/' + job['id'] + '/visibility', json={'published': True}).status_code == 200
    assert candidate.post('/resumes', json={'name': '期待验证简历 · 合成', 'text': '本科软件工程。项目中使用 Python 和 FastAPI 开发订单接口，负责异常校验与测试。', 'data_origin': 'synthetic'}).status_code == 200

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8029)
