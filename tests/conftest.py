import sys
import os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings


def pytest_configure(config):
    # Windows system TEMP is inaccessible in this workspace; isolate owned test files here.
    if not config.option.basetemp:
        workspace = Path(__file__).resolve().parents[1]
        target = (workspace / 'artifacts' / 'pytest-default' / str(os.getpid())).resolve()
        if not target.is_relative_to(workspace / 'artifacts'):
            raise ValueError('测试临时路径必须位于当前工作区 artifacts 内')
        target.parent.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(target)


@pytest.fixture
def client(tmp_path):
    settings=Settings(data_dir=tmp_path,env="demo",auto_seed=True)
    settings.llm_mode="demo"
    with TestClient(create_app(settings)) as test:
        yield test
