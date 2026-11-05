"""Isolated browser QA only. Never imported by app or start.py, never sends a real SMS."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from app.main import create_app
from app.settings import Settings
from auth_helpers import FakeSMS

folder=Path(__file__).resolve().parents[1]/'artifacts'/'auth-password-browser-qa'
settings=Settings(data_dir=folder,env='dev',auto_seed=False)
settings.llm_mode='demo';settings.vector=False
app=create_app(settings)


class PreviewSMS(FakeSMS):
    def send(self,phone):
        super().send(phone)
        (folder/'latest-code.txt').write_text(self.codes[phone],encoding='utf-8')


app.state.auth.sms=PreviewSMS()
if __name__=='__main__': uvicorn.run(app,host='127.0.0.1',port=8017)
