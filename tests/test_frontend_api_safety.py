from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.deterministic import parse_jd
from app.models import ResumeInput
import pytest


def test_production_demo_headers_cannot_read_business_data(tmp_path):
    settings = Settings(data_dir=tmp_path, env='prod', auto_seed=False)
    with TestClient(create_app(settings)) as client:
        assert client.get('/health').status_code == 200
        for path in ['/jobs','/resumes','/assessments','/config/packs','/audit/summary']:
            response = client.get(path, headers={'X-Demo-Actor':'enterprise:demo'})
            assert response.status_code == 401
            assert response.json()['detail']['code'] == 'AUTH_REQUIRED'


def test_each_comparison_jd_is_validated(client):
    response = client.post('/compare/rank', headers={'X-Test-Account':'candidate:lin'}, json={'resume_id':'ignored','job_texts':['太短','完整岗位描述：熟悉 Python 后端开发，负责相关接口与项目。']})
    assert response.status_code == 422
    assert 'body.job_texts.0' in [r['field'] for r in response.json()['detail']['fields']]


def test_upload_count_limit_does_not_create_partial_records(client):
    before = len(client.get('/resumes').json())
    files = [('files',(f'{i}.txt','课程项目中使用 Python 实现数据处理功能。'.encode(),'text/plain')) for i in range(51)]
    response = client.post('/resumes/batch', files=files)
    assert response.status_code == 422
    assert len(client.get('/resumes').json()) == before


def test_title_skill_mention_does_not_override_explicit_requirement():
    profile = parse_jd('Python 工程师\n岗位职责：负责 API 开发。\n任职要求：本科，熟悉 Python 和 FastAPI。')
    python = next(r for r in profile['requirements'] if r['skill']=='Python')
    assert python['required_level']==2
    assert python['quote']=='任职要求：本科，熟悉 Python 和 FastAPI'
    assert parse_jd('数据应用工程师\n岗位要求：熟悉 Python 和 SQL，开发数据分析应用。')['direction']=='数据与算法'


def test_failed_raw_file_write_rolls_back_resume_and_candidate(client, monkeypatch):
    svc=client.app.state.service
    before={t:len(svc.db.list(t)) for t in ('resumes','candidates','audit_logs')}
    from pathlib import Path
    original=Path.write_text
    def fail_raw(path,*args,**kwargs):
        if path.parent.name=='raw_files': raise OSError('模拟磁盘写入失败')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'write_text',fail_raw)
    with pytest.raises(OSError):
        svc.create_resume(ResumeInput(name='合成故障测试',text='课程项目中使用 Python 实现数据处理功能。'),'enterprise:demo')
    assert all(len(svc.db.list(t))==count for t,count in before.items())
