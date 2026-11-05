import sys
import os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from auth_helpers import FakeSMS, sign_in


class ScenarioClient(TestClient):
    """Legacy scenarios choose actual issued sessions, never an app authentication bypass."""
    scenario_sessions = None

    def request(self, method, url, **kwargs):
        if self.scenario_sessions is not None and not str(url).startswith('/auth/'):
            headers = dict(kwargs.pop('headers', None) or {})
            actor = headers.pop('X-Test-Account', 'enterprise:demo')
            cookie, csrf, scope = self.scenario_sessions[actor]
            headers.update({'Cookie': ('tongpin_admin_session=' if scope == 'admin' else 'tongpin_session=') + cookie, 'X-CSRF-Token': csrf, 'X-Session-Scope': scope})
            kwargs['headers'] = headers
        return super().request(method, url, **kwargs)


def pytest_configure(config):
    # Windows system TEMP is inaccessible in this workspace; isolate owned test files here.
    if not config.option.basetemp:
        workspace = Path(__file__).resolve().parents[1]
        target = (workspace / 'artifacts' / 'pytest-default' / str(os.getpid())).resolve()
        if not target.is_relative_to(workspace / 'artifacts'):
            raise ValueError('测试临时路径必须位于当前工作区 artifacts 内')
        target.parent.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(target)


@pytest.fixture(autouse=True)
def isolate_model_environment(monkeypatch):
    # Unit tests never inherit live credentials or model selection from a developer .env.
    for name, value in {'LLM_MODE':'demo','DEEPSEEK_API_KEY':'','RELAY_API_KEY':'',
                        'LLM_DEFAULT_MODEL_ID':'deepseek','LLM_PROFILES_JSON':'[]','RELAY_RESPONSES_STREAM':'false'}.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def client(tmp_path):
    settings=Settings(data_dir=tmp_path,env="demo",auto_seed=True)
    settings.llm_mode="demo"
    with ScenarioClient(create_app(settings)) as test:
        test.app.state.auth.sms = FakeSMS()
        sessions = {}
        for i, actor in enumerate(('enterprise:demo', 'candidate:lin', 'candidate:zhou', 'candidate:chen')):
            test.cookies.clear()
            user = sign_in(test, '1380000000' + str(i), 'enterprise' if i == 0 else 'candidate')
            # Only these scenario fixtures bind seeded records. Runtime registration never does.
            with test.app.state.auth.tx() as cx:
                cx.execute('UPDATE accounts SET actor=?,role=? WHERE id=?', (actor, 'admin' if i == 0 else 'candidate', user['id']))
                cx.execute('UPDATE account_workspaces SET actor=? WHERE account_id=? AND role=?', (actor, user['id'], 'enterprise' if i == 0 else 'candidate'))
            if i == 0:
                result = test.post('/auth/admin/login/password', json={'phone':'13800000000','password':'Scenario-password-2026'})
                assert result.status_code == 200, result.text
                test.headers['X-CSRF-Token'] = result.json()['csrf_token']
            scope = 'admin' if i == 0 else 'user'
            sessions[actor] = (test.cookies.get('tongpin_admin_session' if i == 0 else 'tongpin_session'), test.headers['X-CSRF-Token'], scope)
        test.scenario_sessions = sessions
        yield test
