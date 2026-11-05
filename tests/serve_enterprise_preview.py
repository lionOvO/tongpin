"""Isolated enterprise UI QA with synthetic identities and evidence; no real SMS."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from auth_helpers import FakeSMS, sign_in
from scripts.manage_accounts import promote
from test_enterprise_verification import PNG, FIELDS

folder=Path(__file__).resolve().parents[1]/'artifacts'/'enterprise-browser-qa'
settings=Settings(data_dir=folder,env='dev',auto_seed=False)
settings.llm_mode='demo';settings.vector=False
app=create_app(settings);app.state.auth.sms=FakeSMS()
if not (folder/'prepared.txt').exists():
    with TestClient(app) as user,TestClient(app) as admin:
        sign_in(user,'13800000801','candidate')
        result=user.post('/enterprise-verification',data=FIELDS,files={'license':('license.png',PNG,'image/png'),'authorization':('authorization.png',PNG,'image/png')})
        assert result.status_code==200,result.text
        sign_in(admin,'13800000803','enterprise');promote(app.state.auth,'13800000803')
    (folder/'prepared.txt').write_text('Synthetic QA only',encoding='utf-8')
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=8017)
