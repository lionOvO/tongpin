"""Phase three browser acceptance: isolated :8528/:8028, synthetic provider."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

OUT = Path(__file__).resolve().parents[1] / 'artifacts' / 'recruiter-agent-phase3'
URL = 'http://127.0.0.1:8528'


def main():
    OUT.mkdir(parents=True, exist_ok=True); errors = []; posts = []; sizes = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' and '/turns/stream' in r.url else None)
        page.goto(URL + '/login?role=enterprise')
        page.locator('input[name=phone]').fill('13800000991')
        page.locator('input[name=password]').fill('Scenario-password-2026')
        page.get_by_role('button', name='登录工作空间', exact=True).click()
        expect(page.locator('.topbar-actions .account-name')).to_be_attached()
        page.get_by_role('link', name='招聘 AI 工作区', exact=False).first.click()
        page.locator('.recruiter-ai-candidate-list button').filter(has_text='陈予安').click()
        expect(page.get_by_label('材料助手', exact=True)).to_be_checked()
        expect(page.get_by_role('button', name='整理简历精华', exact=True).first).to_be_enabled()
        page.evaluate("""() => { window.previews = []; new MutationObserver(() => {
          const text = document.querySelector('.recruiter-stream-preview p')?.textContent;
          if (text && window.previews.at(-1) !== text) window.previews.push(text);
        }).observe(document.body, {childList:true,subtree:true,characterData:true}) }""")
        page.get_by_role('button', name='整理简历精华', exact=True).first.click()
        page.get_by_role('button', name='查看建议并整理提纲', exact=True).wait_for(timeout=20000)
        previews = page.evaluate('window.previews')
        assert len(previews) > 2, previews
        progress = page.locator('.recruiter-agent-progress')
        progress.locator('summary').click()
        expect(progress.locator('li')).to_have_count(5)
        expect(progress).to_contain_text('已完成')
        expect(page.locator('.plan-question')).to_have_count(0)
        page.screenshot(path=str(OUT / 'desktop-tools.png'), full_page=True)
        page.get_by_role('button', name='查看建议并整理提纲', exact=True).click()
        page.get_by_role('button', name='加入提纲', exact=True).click()
        page.locator('.plan-notes textarea').fill('围绕职责、实现过程和核对方法沟通。')
        page.get_by_role('button', name='保存提纲', exact=True).click()
        expect(page.get_by_role('button', name='保存提纲', exact=True)).to_be_disabled()
        with page.expect_download() as download:
            page.locator('.plan-footer').get_by_role('button', name='导出', exact=True).click()
        download.value.save_as(OUT / 'outline.md')
        assert 'FastAPI' in (OUT / 'outline.md').read_text(encoding='utf-8-sig')
        page.reload()
        page.get_by_role('button', name='分析与面试提纲', exact=True).click()
        page.get_by_role('button', name='面试提纲 1', exact=True).click()
        expect(page.locator('.plan-notes textarea')).to_have_value('围绕职责、实现过程和核对方法沟通。')
        page.get_by_role('button', name='AI 对话', exact=True).click()
        # Resume an in-flight run through GET, without replaying a paid POST.
        page.locator('#recruiter-question').fill('结合业务背景再整理一次。')
        page.locator('.recruiter-composer button[type=submit]').click()
        page.get_by_role('button', name='停止', exact=True).wait_for()
        page.reload()
        expect(page.locator('.recruiter-chat-message.assistant')).to_have_count(2, timeout=20000)
        assert len(posts) == 2, posts
        expect(page.locator('.recruiter-composer button[type=submit]')).to_be_enabled()
        # Cancel and keep input, then retry after a provider failure.
        page.locator('#recruiter-question').fill('请继续分析订单接口。')
        page.locator('.recruiter-composer button[type=submit]').click()
        page.get_by_role('button', name='停止', exact=True).click()
        expect(page.locator('.recruiter-chat-success')).to_contain_text('已停止')
        expect(page.locator('.recruiter-composer button[type=submit]')).to_be_enabled(timeout=12000)
        expect(page.locator('#recruiter-question')).to_have_value('请继续分析订单接口。')
        expect(page.locator('.recruiter-chat-message.assistant')).to_have_count(2)
        page.locator('#recruiter-question').fill('测试失败')
        page.locator('.recruiter-composer button[type=submit]').click()
        expect(page.locator('.recruiter-chat-error')).to_be_visible(timeout=15000)
        expect(page.locator('#recruiter-question')).to_have_value('测试失败')
        expect(page.locator('.recruiter-stream-preview')).to_have_count(0)
        page.locator('#recruiter-question').fill('请再给出建议。')
        page.locator('.recruiter-composer button[type=submit]').click()
        expect(page.locator('.recruiter-chat-message.assistant')).to_have_count(3, timeout=20000)
        # Explicit ordinary conversation fallback stays compatible.
        page.get_by_label('材料助手', exact=True).uncheck()
        page.get_by_role('button', name='整理简历精华', exact=True).first.click()
        expect(page.locator('.recruiter-chat-message.assistant')).to_have_count(4)
        page.get_by_label('材料助手', exact=True).check()
        page.get_by_role('button', name='新对话', exact=True).click()
        page.get_by_role('button', name='保存并新建', exact=True).click()
        expect(page.locator('.recruiter-chat-start')).to_be_visible()
        page.get_by_role('button', name='对话历史', exact=True).click()
        page.locator('.recruiter-session-list button').filter(has_text='整理这份简历').click()
        expect(page.locator('.recruiter-chat-archive')).to_be_visible()
        expect(page.locator('.recruiter-agent-progress')).to_have_count(0)
        expect(page.locator('#recruiter-question')).to_be_disabled()
        # Candidate switching cannot carry the prior conversation or plan.
        page.locator('.recruiter-ai-candidate-list button').filter(has_text='林知夏').click()
        expect(page.locator('.recruiter-chat-start')).to_be_visible()
        expect(page.locator('.plan-question')).to_have_count(0)
        page.get_by_role('button', name='整理简历精华', exact=True).first.click()
        expect(page.locator('.recruiter-chat-message.assistant')).to_have_count(1, timeout=20000)
        expect(page.locator('.recruiter-chat-message.assistant')).to_contain_text('Vue 3')
        assert 'FastAPI' not in page.locator('.recruiter-chat-message.assistant').inner_text()
        for width, height in [(1440, 1000), (1366, 768), (1024, 768), (390, 844), (360, 740)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.wait_for_timeout(180)
            geometry = page.evaluate("""({width:innerWidth, scroll:document.documentElement.scrollWidth,
              bottom:document.querySelector('.recruiter-composer').getBoundingClientRect().bottom, height:innerHeight})""")
            assert geometry['scroll'] <= width and geometry['bottom'] <= height+1, geometry
            sizes.append(geometry)
            if width == 390: page.screenshot(path=str(OUT / 'mobile.png'), full_page=True)
        page.get_by_role('button', name='切换候选人', exact=True).click()
        page.locator('#recruiter-ai-search').fill('周启明')
        page.locator('.recruiter-ai-candidate-list button').filter(has_text='周启明').click()
        expect(page.locator('.recruiter-chat-start')).to_be_visible()
        page.emulate_media(reduced_motion='no-preference')
        expect(page.locator('.recruiter-composer')).to_be_visible()
        assert not errors, errors
        browser.close()
    result = {'passed': True, 'stream_updates': len(previews), 'generation_posts': len(posts), 'sizes': sizes,
        'checks': ['stream and actual tools', 'human-selected saved outline', 'reload and export', 'refresh in flight without replay',
            'stop preserves input', 'failure clears preview and retry', 'ordinary fallback', 'read-only archive', 'candidate isolation',
            'desktop and mobile layout', 'reduced motion'], 'page_errors': errors}
    (OUT / 'browser.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
