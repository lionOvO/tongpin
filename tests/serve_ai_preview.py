"""Isolated browser QA using synthetic data and the configured model.

Run manually, never as part of pytest. It does not seed production accounts.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from auth_helpers import FakeSMS, sign_in

folder = Path(__file__).resolve().parents[1] / 'artifacts' / 'ai-browser-qa'
settings = Settings(data_dir=folder, env='dev', auto_seed=False)
settings.vector = False
app = create_app(settings); app.state.auth.sms = FakeSMS()
with app.state.auth.tx() as cx:
    exists = cx.execute('SELECT id FROM accounts WHERE env=? AND phone=?', ('dev','13800000981')).fetchone()
if not exists:
    with TestClient(app) as client:
        sign_in(client, '13800000981')
        client.post('/resumes', json={'name': '合成示例 · 后端开发', 'data_origin': 'synthetic',
            'text': '专业：软件工程，本科在读。\n技能：Python、SQL，了解 FastAPI。\n项目：使用 Python 和 SQLite 开发图书借阅服务，负责借阅及归还接口、数据库表设计，并使用 pytest 编写接口测试。\n项目：小组合作完成课程作业，我主要负责后端；没有记录接口响应时间和使用人数。\n求职方向：后端开发，希望在真实业务中积累服务开发经验。'})
if __name__ == '__main__': uvicorn.run(app, host='127.0.0.1', port=8018)
