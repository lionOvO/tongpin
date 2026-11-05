"""Isolated :8527/:8027 browser acceptance. No live business accounts or paid calls."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / 'artifacts' / 'material-agent-phase2'


def main():
    OUT.mkdir(parents=True, exist_ok=True); errors = []; posts = []; sizes = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' and '/turns/stream' in r.url else None)
        page.goto('http://127.0.0.1:8527/login')
        page.locator('#auth-phone').fill('13800000981'); page.locator('#auth-password').fill('Scenario-password-2026')
        page.locator('form button.primary').click(); page.wait_for_url('**/workspace')
        page.goto('http://127.0.0.1:8527/ai-workspace'); page.locator('#ai-message').wait_for()
        page.evaluate("""() => { window.previews = []; new MutationObserver(() => {
          const text = document.querySelector('.ai-stream-message p')?.textContent;
          if (text && window.previews.at(-1) !== text) window.previews.push(text);
        }).observe(document.body, {childList:true,subtree:true,characterData:true}) }""")
        page.locator('#ai-message').fill('请优化简历项目描述，生成前后对比。')
        page.get_by_role('button', name='发送消息', exact=True).click()
        page.get_by_role('button', name='查看修改前后', exact=False).wait_for(timeout=25000)
        previews = page.evaluate('window.previews')
        assert len(previews) >= 2, previews
        page.get_by_role('button', name='查看修改前后', exact=False).click()
        assert page.locator('.ai-revision').count() == 2
        assert page.locator('.ai-revision ins').count() >= 1 and page.locator('.ai-revision del').count() >= 1
        page.locator('.ai-revision-choice input').nth(1).uncheck()
        page.get_by_role('button', name='手动调整', exact=True).first.click()
        page.get_by_label('建议内容 1', exact=True).fill('项目：使用 Python 开发图书借阅服务，负责接口编写和测试。')
        page.get_by_role('button', name='完成调整', exact=True).click()
        page.screenshot(path=str(OUT / 'desktop-diff.png'), full_page=True)
        page.get_by_role('button', name='确认并保存为新版本', exact=False).click()
        page.locator('.modal').wait_for(); page.get_by_role('button', name='确认采纳并使用优化版', exact=True).click()
        page.get_by_text('优化版已保存，原件保留', exact=True).wait_for()
        assert '优化版' in page.locator('.ai-chat-heading h2').inner_text()
        page.reload(); page.locator('#ai-message').wait_for()
        assert '优化版' in page.locator('.ai-chat-heading h2').inner_text()
        page.get_by_role('button', name='对话', exact=True).click()
        page.get_by_role('button', name='找岗位并对照', exact=True).click()
        page.locator('.ai-comparison-progress').wait_for(timeout=20000)
        # Reload while a durable comparison is running, without replaying Agent POST.
        assert len(posts) == 2
        task_url = page.url; page.reload()
        page.wait_for_function("document.querySelectorAll('.ai-job-result').length >= 2", timeout=20000)
        page.get_by_text('分析已完成', exact=True).wait_for(timeout=20000)
        assert page.url == task_url and len(posts) == 2
        assert page.locator('.ai-fit-band').all_text_contents() == ['较高契合', '一般契合', '一般契合']
        page.screenshot(path=str(OUT / 'desktop-jobs.png'), full_page=True)
        for w, h in [(1440, 1000), (1024, 768), (390, 844), (360, 740)]:
            page.set_viewport_size({'width': w, 'height': h}); page.wait_for_timeout(150)
            size = page.evaluate("({width:innerWidth, scroll:document.documentElement.scrollWidth, composer:document.querySelector('.ai-composer').getBoundingClientRect().bottom, height:innerHeight})")
            assert size['scroll'] <= w and size['composer'] <= h, size
            sizes.append(size)
            if w == 390: page.screenshot(path=str(OUT / 'mobile-jobs.png'), full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.locator('.ai-job-result button').first.click()
        page.wait_for_function("document.querySelector('.ai-chat-heading h2').textContent.includes('Python')", timeout=10000)
        page.get_by_role('button', name='查看修改前后', exact=False).wait_for(timeout=25000)
        page.get_by_role('button', name='查看修改前后', exact=False).click()
        page.set_viewport_size({'width': 390, 'height': 844}); page.wait_for_timeout(150)
        assert page.locator('.ai-revision').count() == 2
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(OUT / 'mobile-diff.png'), full_page=True)
        page.get_by_role('button', name='对话', exact=True).click()
        count = page.locator('.ai-message.assistant:not(.ai-stream-message)').count()
        page.locator('#ai-message').fill('停止测试')
        page.get_by_role('button', name='发送消息', exact=True).click()
        page.get_by_role('button', name='停止', exact=True).click(timeout=10000)
        page.wait_for_function("!document.querySelector('#ai-message').disabled", timeout=10000)
        assert page.locator('.ai-message.assistant:not(.ai-stream-message)').count() == count
        page.locator('#ai-message').fill('失败测试')
        page.get_by_role('button', name='发送消息', exact=True).click()
        page.get_by_text('可以重新发送问题重试，已有材料与结果保留。', exact=True).wait_for(timeout=12000)
        assert page.locator('#ai-message').input_value() == '失败测试'
        assert page.locator('.ai-stream-message').count() == 0
        assert not errors, errors
        browser.close()
    result = {'stream_updates': len(previews), 'agent_posts': len(posts), 'viewports': sizes, 'page_errors': errors,
        'checks': ['real incremental preview', 'highlighted diff', 'selective adoption', 'manual edits', 'explicit save and switch',
            'background comparison', 'reload without replay', 'five-band cards', 'job-specific optimization', 'cancel', 'failure preserves input']}
    (OUT / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
