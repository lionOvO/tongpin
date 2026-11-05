"""Prevent a successful dev launch with an empty or incomplete Vue entry."""
from pathlib import Path
import pytest
import start


def test_current_vue_entry_is_bootable():
    start.validate_frontend_entry(Path(__file__).resolve().parents[1] / 'frontend')


def test_local_api_reloads_only_application_code_and_preserves_selected_port():
    command = start.build_api_command(Path('runtime/python.exe'), 8001)
    assert command[:4] == [str(Path('runtime/python.exe')), '-m', 'uvicorn', 'app.main:app']
    assert command[command.index('--port') + 1] == '8001'
    assert '--reload' in command
    assert command[command.index('--reload-dir') + 1] == str(start.ROOT / 'app')
    assert not any('data' == Path(arg).name or 'artifacts' == Path(arg).name for arg in command)


def test_local_api_reload_can_be_disabled_explicitly():
    assert '--reload' not in start.build_api_command('python', 8000, reload=False)


@pytest.mark.parametrize('html', [
    '',
    '<html><body><div id="app"></div></body></html>',
    '<html><body><script type="module" src="/src/main.ts"></script></body></html>',
])
def test_launcher_rejects_empty_or_incomplete_entry_before_install(tmp_path, monkeypatch, html):
    folder=tmp_path/'frontend'
    folder.mkdir()
    (folder/'index.html').write_text(html, encoding='utf-8')
    (folder/'src').mkdir()
    (folder/'src'/'main.ts').write_text('', encoding='utf-8')
    monkeypatch.setattr(start, 'ROOT', tmp_path)
    def unexpected_lookup(*args):
        pytest.fail('Broken entry must be rejected before dependency lookup/install')
    monkeypatch.setattr(start.shutil, 'which', unexpected_lookup)
    with pytest.raises(RuntimeError, match='前端入口缺失或损坏'):
        start.ensure_frontend()


def test_missing_entry_module_is_rejected(tmp_path):
    (tmp_path/'index.html').write_text('<div id="app"></div><script type="module" src="/src/main.ts"></script>',encoding='utf-8')
    with pytest.raises(RuntimeError, match='前端入口缺失或损坏'):
        start.validate_frontend_entry(tmp_path)


def test_source_stamp_detects_code_changes_but_ignores_runtime_data(tmp_path,monkeypatch):
    monkeypatch.setattr(start,'ROOT',tmp_path)
    (tmp_path/'app').mkdir(); (tmp_path/'data').mkdir()
    source=tmp_path/'app'/'main.py'; source.write_text('first')
    before=start.api_source_stamp()
    (tmp_path/'data'/'runtime.log').write_text('runtime')
    (tmp_path/'app'/'ignored.json').write_text('{}')
    assert start.api_source_stamp()==before
    source.write_text('updated source')
    assert start.api_source_stamp()!=before
