"""Browser acceptance for recruiter workbench, only isolated synthetic :8519."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts' / 'recruiter-workspace-three-pane'
URL = 'http://127.0.0.1:8519'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Users\86185\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe', headless=True, args=['--disable-gpu'])
        page = browser.new_page(viewport={'width': 1920, 'height': 1080}, reduced_motion='reduce')
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(URL + '/login?role=enterprise')
        page.locator('input[name=phone]').fill('13800000991')
        page.locator('input[name=password]').fill('Scenario-password-2026')
        page.get_by_role('button', name='登录工作空间', exact=True).click()
        expect(page.locator('.topbar-actions .account-name')).to_be_attached()
        page.get_by_role('link', name='招聘 AI 工作区', exact=False).first.click()
        page.locator('.recruiter-ai-candidate-list button').filter(has_text='陈予安').click()
        summary = page.get_by_role('button', name='整理简历精华', exact=True).first
        expect(summary).to_be_enabled()
        expect(page.locator('.recruiter-ai-subject .recruiter-chat-tools')).to_have_count(1)
        expect(page.locator('.recruiter-chat .recruiter-chat-tools')).to_have_count(0)
        expect(page.locator('.recruiter-ai-subject').get_by_role('button', name='刷新对话', exact=True)).to_have_count(1)
        expect(page.locator('.recruiter-ai-subject').get_by_role('button', name='刷新投递', exact=True)).to_have_count(0)
        action_styles = page.locator('.recruiter-ai-subject .recruiter-header-action').evaluate_all("els => els.map(el => { const s = getComputedStyle(el); return [s.color, s.backgroundColor, s.borderColor, s.height, s.fontSize].join('|') })")
        assert len(action_styles) == 6 and len(set(action_styles)) == 1, action_styles
        name_box = page.locator('.recruiter-subject-name').bounding_box()
        tools_box = page.locator('.recruiter-subject-toolbar').bounding_box()
        assert name_box and tools_box and abs(name_box['y'] + name_box['height']/2 - tools_box['y'] - tools_box['height']/2) < 3
        expect(page.locator('.recruiter-ai-candidates')).to_be_visible()
        expect(page.locator('.recruiter-results')).to_be_visible()
        page.screenshot(path=str(OUT / 'desktop-default.png'), full_page=True)
        source = page.locator('.recruiter-current-materials details').first
        source.locator('summary').click()
        expect(source.locator('.recruiter-source-preview')).to_contain_text('FastAPI')
        expect(page.locator('.recruiter-chat')).to_be_visible()
        source.locator('summary').click()
        initial_count = page.locator('.recruiter-chat-message.assistant').count()
        summary.click()
        expect(page.locator('.recruiter-result-dot')).to_be_visible()
        expect(page.locator('.recruiter-chat')).to_be_visible()
        followups = page.locator('.recruiter-followups').last
        expect(followups).not_to_have_attribute('open', '')
        followups.locator('summary').click()
        followups.get_by_role('button').first.click()
        expect(page.locator('#recruiter-question')).not_to_have_value('')
        followups.locator('summary').click()
        expect(page.locator('.result-answer')).to_contain_text('实际负责的任务')
        expect(page.locator('.result-evidence blockquote')).to_contain_text('FastAPI')
        page.get_by_role('button', name='展开阅读', exact=True).click()
        expect(page.locator('.recruiter-chat')).not_to_be_visible()
        page.screenshot(path=str(OUT / 'desktop-results.png'), full_page=True)
        page.get_by_role('button', name='返回对话', exact=True).click()
        expect(page.locator('.recruiter-chat')).to_be_visible()
        page.get_by_role('button', name='补充业务背景', exact=True).click()
        page.locator('#recruiter-business-input').fill('维护订单接口，核对查询结果。')
        page.get_by_role('button', name='保存业务背景', exact=True).click()
        expect(page.locator('.recruiter-chat-success')).to_contain_text('业务背景已保存')
        page.get_by_role('button', name='收起业务背景').click()
        page.get_by_role('button', name='准备面试追问', exact=True).click()
        expect(page.locator('.recruiter-chat-message.assistant')).to_have_count(initial_count + 2)
        page.locator('.recruiter-chat-log').evaluate('(el) => el.scrollTop = el.scrollHeight')
        page.screenshot(path=str(OUT / 'desktop-conversation.png'), full_page=True)
        page.get_by_role('button', name='分析与面试提纲', exact=True).click()
        expect(page.locator('.result-kind')).to_have_text('面试追问')
        page.get_by_role('button', name='加入提纲', exact=True).click()
        expect(page.locator('.plan-question')).to_have_count(1)
        page.locator('.plan-notes textarea').fill('核对实现过程，并讨论协作方式。')
        page.get_by_role('button', name='保存提纲', exact=True).click()
        expect(page.locator('.recruiter-chat-success')).to_contain_text('面试提纲已保存')
        expect(page.get_by_role('button', name='保存提纲', exact=True)).to_be_disabled()
        with page.expect_download() as download:
            page.locator('.plan-footer').get_by_role('button', name='导出', exact=True).click()
        target = OUT / 'interview-outline.md'
        download.value.save_as(target)
        text = target.read_text(encoding='utf-8-sig')
        assert '核对实现过程' in text and '已授权简历' in text and 'FastAPI' in text
        page.screenshot(path=str(OUT / 'desktop-workbench.png'), full_page=True)
        page.reload()
        expect(summary).to_be_enabled()
        page.get_by_role('button', name='分析与面试提纲', exact=True).click()
        page.get_by_role('button', name='面试提纲 1', exact=True).click()
        expect(page.locator('.plan-notes textarea')).to_have_value('核对实现过程，并讨论协作方式。')
        page.get_by_role('button', name='AI 对话', exact=True).click()
        page.get_by_role('button', name='新对话', exact=True).click()
        page.get_by_role('button', name='保存并新建', exact=True).click()
        expect(page.locator('.recruiter-chat-start')).to_be_visible()
        expect(page.locator('.plan-question')).to_have_count(0)
        page.get_by_role('button', name='对话历史', exact=True).click()
        dialog = page.get_by_role('dialog')
        dialog.locator('input').fill('整理这份简历')
        expect(dialog.locator('.recruiter-session-list button')).to_have_count(1)
        dialog.locator('.recruiter-session-list button').click()
        expect(page.locator('.recruiter-chat-archive')).to_be_visible()
        expect(page.locator('#recruiter-question')).to_be_disabled()
        page.get_by_role('button', name='分析与面试提纲', exact=True).click()
        expect(page.locator('.plan-question')).to_have_count(1)
        expect(page.locator('.plan-notes textarea')).to_be_disabled()
        page.get_by_role('button', name='AI 对话', exact=True).click()
        page.get_by_role('button', name='对话历史', exact=True).click()
        with page.expect_download() as download:
            page.get_by_role('button', name='导出所选对话', exact=True).click()
        download.value.save_as(OUT / 'conversation.md')
        page.get_by_role('button', name='删除所选对话', exact=True).click()
        page.get_by_role('button', name='确认删除对话', exact=True).click()
        expect(page.locator('.recruiter-chat-start')).to_be_visible()
        expect(page.locator('.recruiter-ai-candidates')).to_be_visible()
        page.screenshot(path=str(OUT / 'desktop-candidate-list.png'), full_page=True)
        page.locator('.recruiter-ai-candidate-list button').filter(has_text='林知夏').click()
        expect(page.locator('.recruiter-chat-start')).to_be_visible()
        page.get_by_role('button', name='授权材料', exact=True).click()
        expect(page.locator('.application-resume-tools')).to_be_visible()
        expect(page.locator('.recruiter-ai-materials')).to_contain_text('Vue 3')
        page.get_by_role('button', name='AI 对话', exact=True).click()
        page.get_by_role('button', name='专注对话', exact=True).click()
        expect(page.locator('.recruiter-ai-candidates')).not_to_be_visible()
        expect(page.locator('.recruiter-results')).not_to_be_visible()
        page.get_by_role('button', name='返回工作台', exact=True).click()
        geometries = []
        for width, height in [(1920, 1080), (1440, 900), (1366, 768), (1280, 800), (390, 844), (360, 740), (844, 390)]:
            page.set_viewport_size({'width': width, 'height': height})
            expect(page.locator('.recruiter-composer')).to_be_visible()
            page.screenshot(path=str(OUT / f'chat-{width}.png'), full_page=True)
            geometry = page.locator('.recruiter-chat-log').bounding_box()
            composer = page.locator('.recruiter-composer').bounding_box()
            assert geometry and composer
            if width >= 1280:
                expect(page.locator('.recruiter-ai-candidates')).to_be_visible()
                expect(page.locator('.recruiter-results')).to_be_visible()
                assert geometry['width'] >= 400, geometry
                assert geometry['height'] >= 200, geometry
            if height > 580:
                assert composer['y'] + composer['height'] <= height + 1, composer
            page.get_by_role('button', name='分析与面试提纲', exact=True).click()
            expect(page.locator('.recruiter-results')).to_be_visible()
            page.screenshot(path=str(OUT / f'workspace-{width}.png'), full_page=True)
            dims = page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
            assert dims['scroll'] <= dims['width'], dims
            geometries.append(dims)
            page.get_by_role('button', name='AI 对话', exact=True).click()
        page.set_viewport_size({'width':390, 'height':844})
        page.get_by_role('button', name='切换候选人', exact=True).click()
        expect(page.locator('#recruiter-ai-search')).to_be_focused()
        page.keyboard.press('Escape')
        expect(page.get_by_role('button', name='切换候选人', exact=True)).to_be_focused()
        page.get_by_role('button', name='切换候选人', exact=True).click()
        page.locator('#recruiter-ai-search').fill('周启明')
        page.locator('.recruiter-ai-candidate-list button').filter(has_text='周启明').click()
        expect(page.locator('.recruiter-ai-subject')).to_contain_text('周启明')
        expect(page.locator('.recruiter-chat-start')).to_be_visible()
        page.emulate_media(reduced_motion='no-preference')
        page.set_viewport_size({'width': 1366, 'height': 768})
        expect(page.locator('.recruiter-ai-candidates')).to_be_visible()
        expect(page.locator('.recruiter-results')).to_be_visible()
        expect(page.locator('.recruiter-composer')).to_be_visible()
        assert not errors, errors
        browser.close()
    result = {'checks': ['three panes with chat toolbar in candidate header', 'save business context', 'select/save/reload interview outline', 'export plan and evidence', 'archive/new conversation', 'history search and read-only restore', 'export and delete selected history', 'candidate isolation', 'authorized download/import controls', 'focus mode', 'responsive 1920/1440/1366/1280/390/360 and short landscape', 'mobile candidate switch'], 'geometry': geometries, 'page_errors': errors}
    (OUT / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
