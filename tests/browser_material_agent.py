"""Manual QA: isolated scripted API :8027, Vite :8527. Never uses live data/models."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / 'artifacts' / 'material-agent'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors = []; turns = []; sizes = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda r: turns.append(r.post_data_json) if r.method == 'POST' and r.url.endswith('/turns') else None)
        page.goto('http://127.0.0.1:8527/login')
        page.locator('#auth-phone').fill('13800000981')
        page.locator('#auth-password').fill('Scenario-password-2026')
        page.locator('form button.primary').click()
        page.wait_for_url('**/workspace')
        page.goto('http://127.0.0.1:8527/ai-workspace')
        page.locator('#ai-message').wait_for()
        assert page.locator('.ai-agent-choice input').is_checked()
        initial_assistants = page.locator('.ai-message.assistant').count()
        page.locator('#ai-message').fill('请定位 Python 项目，对照当前岗位，并生成表达优化草稿。')
        page.get_by_role('button', name='发送消息', exact=True).click()
        page.get_by_role('button', name='停止', exact=True).wait_for()
        # Reload while POST is executing. GET/poll must recover the result without replaying it.
        page.reload()
        page.get_by_text('草稿已准备，请核对后确认保存。', exact=True).wait_for(timeout=20000)
        assert len(turns) == 1 and turns[0]['agent'] is True
        page.locator('.ai-agent-progress summary').click()
        assert page.locator('.ai-agent-progress li').count() == 4
        page.get_by_role('button', name='结果与草稿', exact=False).click()
        page.get_by_role('button', name='修改草稿', exact=False).click()
        page.get_by_role('button', name='确认并保存为新版本', exact=True).wait_for()
        assert page.locator('.ai-before').inner_text().find('图书借阅') >= 0
        page.screenshot(path=str(OUT / 'desktop-draft.png'), full_page=True)
        page.get_by_role('button', name='确认并保存为新版本', exact=True).click()
        page.locator('.modal').wait_for()
        page.locator('.modal button.primary').click()
        page.get_by_text('优化版已保存，原件保留', exact=True).wait_for()
        page.get_by_role('button', name='对话', exact=True).click()
        for w, h in [(1440, 1000), (1024, 768), (768, 1024), (390, 844), (360, 740)]:
            page.set_viewport_size({'width': w, 'height': h})
            page.wait_for_timeout(180)
            size = page.evaluate("({width:innerWidth,scroll:document.documentElement.scrollWidth,composer:document.querySelector('.ai-composer').getBoundingClientRect().bottom,height:innerHeight})")
            assert size['scroll'] <= size['width'], size
            assert size['composer'] <= size['height'], size
            sizes.append(size)
            if w == 390: page.screenshot(path=str(OUT / 'mobile.png'), full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.locator('#ai-message').fill('停止测试：先看看项目表达。')
        page.get_by_role('button', name='发送消息', exact=True).click()
        page.get_by_role('button', name='停止', exact=True).click(timeout=10000)
        page.get_by_text('已停止；原材料未改变，可以重新发送问题。', exact=True).wait_for()
        page.wait_for_function("!document.querySelector('#ai-message').disabled", timeout=10000)
        assert page.locator('.ai-message.assistant').count() == initial_assistants + 1
        # Retry after an actual failed execution retains the composed question.
        page.locator('#ai-message').fill('失败测试')
        page.get_by_role('button', name='发送消息', exact=True).click()
        page.get_by_text('可以重新发送问题重试，已有材料与结果保留。', exact=True).wait_for()
        assert page.locator('#ai-message').input_value() == '失败测试'
        page.locator('#ai-message').fill('再次优化项目表达。')
        page.get_by_role('button', name='发送消息', exact=True).click()
        page.get_by_text('草稿已准备，请核对后确认保存。', exact=True).wait_for(timeout=15000)
        assert page.locator('.ai-message.assistant').count() == initial_assistants + 2
        assert not errors, errors
        browser.close()
    result = {'viewports': sizes, 'page_errors': errors, 'turns': len(turns),
        'checks': ['default agent', 'live progress', 'reload without replay', 'four actual tools', 'draft diff',
                   'explicit confirmation saves', 'cancel fences late result', 'failure preserves input', 'retry', 'mobile composer visible']}
    (OUT / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
