"""Isolated local WebRTC QA. Synthetic accounts, fake SMS, no external model calls."""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from auth_helpers import FakeSMS, sign_in
from test_auth_isolation import create_job, create_resume
from test_hiring import apply_body, change

ROOT = Path(__file__).resolve().parents[1]
folder = ROOT / 'artifacts' / 'video-call-qa'
settings = Settings(data_dir=folder / str(os.getpid()), env='dev', auto_seed=False)
settings.llm_mode = 'demo'; settings.vector = False; settings._session_cookie_secure = False
app = create_app(settings); app.state.auth.sms = FakeSMS()
with TestClient(app) as company, TestClient(app) as candidate:
    sign_in(company, '13800000651', 'enterprise')
    sign_in(candidate, '13800000652', 'candidate')
    job = create_job(company)
    company.put('/jobs/' + job['id'] + '/visibility', json={'published': True})
    resume = create_resume(candidate)
    row = candidate.post('/applications', json=apply_body(job, resume)).json()
    row = change(company, row, 'invite', '你好，想通过视频进一步了解你的项目经历和岗位期待。').json()
    row = change(candidate, row, 'accept').json()
    (folder / 'latest.json').write_text(json.dumps({'application_id': row['id'], 'data_dir': str(settings.data_dir)}, ensure_ascii=False), encoding='utf8')
if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8025)
