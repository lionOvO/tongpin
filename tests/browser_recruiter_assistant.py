"""Manual browser QA against serve_recruiter_preview.py and isolated Vite :8519.

Uses only the synthetic fixture account. Never targets the normal app ports.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts' / 'local-runtime'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:8519/login?role=enterprise')
        page.locator('#auth-phone').fill('13800000991')
        page.locator('#auth-password').fill('Scenario-password-2026')
        page.locator('form button.primary').click()
        page.wait_for_url('**/workspace')
        page.get_by_role('link', name='招聘 AI 工作区', exact=False).first.click()
        page.get_by_role('button', name='整理简历精华', exact=True).wait_for()
        assert page.locator('.recruiter-ai-candidate-list button').count() == 3
        # Open the fixture containing the Python/FastAPI project and existing card.
        page.locator('.recruiter-ai-candidate-list button').filter(has_text='陈予安').click()
        page.wait_for_function("document.querySelector('.recruiter-shortcuts button')?.disabled === false")
        initial_count = page.locator('.recruiter-chat-message.assistant').count()
        page.get_by_role('button', name='整理简历精华', exact=True).click()
        page.wait_for_function("count => document.querySelectorAll('.recruiter-chat-message.assistant').length === count", arg=initial_count + 1)
        page.get_by_text('查看原文依据 · 1 处', exact=True).last.click()
        assert 'FastAPI' in page.locator('.recruiter-chat-citations blockquote').last.inner_text()
        page.locator('#recruiter-question').fill('面试时应怎样了解这段项目职责？')
        page.get_by_role('button', name='发送', exact=True).click()
        page.wait_for_function("count => document.querySelectorAll('.recruiter-chat-message.assistant').length === count", arg=initial_count + 2)
        page.reload()
        page.wait_for_function("count => document.querySelectorAll('.recruiter-chat-message.assistant').length === count", arg=initial_count + 2)
        assert f'已有 AI 对话 · {(initial_count + 2) * 2} 条' in page.locator('.recruiter-ai-candidate-list').inner_text()
        page.locator('.recruiter-ai-candidate-list button').filter(has_text='林知夏').click()
        page.get_by_text('从具体经历开始了解。', exact=True).wait_for()
        assert page.locator('.recruiter-chat-message').count() == 0
        page.locator('.recruiter-ai-candidate-list button').filter(has_text='陈予安').click()
        page.wait_for_function("count => document.querySelectorAll('.recruiter-chat-message.assistant').length === count", arg=initial_count + 2)
        page.get_by_role('button', name='资料卡与技术图谱', exact=True).click()
        page.locator('.recruiter-ai-profile .recruiter-profile').wait_for()
        page.locator('.recruiter-ai-profile').get_by_text('核心技术经历', exact=True).wait_for()
        page.get_by_role('button', name='授权材料', exact=True).click()
        assert 'FastAPI' in page.locator('.recruiter-ai-materials').inner_text()
        page.get_by_role('button', name='AI 对话', exact=True).click()
        page.screenshot(path=str(OUT / 'recruiter-ai-workspace.jpg'), full_page=True)
        desktop = page.evaluate("({width: innerWidth, scroll: document.documentElement.scrollWidth, chat: document.querySelector('.recruiter-chat-log').clientHeight})")
        page.get_by_role('button', name='专注对话', exact=True).click()
        page.wait_for_function("document.querySelector('.recruiter-ai-page').classList.contains('recruiter-ai-focused')")
        page.screenshot(path=str(OUT / 'recruiter-ai-focused.jpg'), full_page=True)
        focus = page.locator('.recruiter-composer').bounding_box()
        assert focus and focus['y'] + focus['height'] <= 1000, focus
        page.get_by_role('button', name='返回工作台', exact=True).click()
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(OUT / 'recruiter-ai-mobile.jpg'), full_page=True)
        mobile = page.evaluate("({width: innerWidth, scroll: document.documentElement.scrollWidth, chat: document.querySelector('.recruiter-chat-log').clientHeight})")
        assert desktop['scroll'] <= desktop['width'] and mobile['scroll'] <= mobile['width'], (desktop, mobile)
        assert not errors, errors
        browser.close()
    print(json.dumps({'desktop': desktop, 'mobile': mobile, 'page_errors': errors, 'checks': ['login and sidebar entry', 'three authorized candidates visible', 'summary with exact citation', 'chat and persisted history', 'separate candidate histories', 'profile and technical graph', 'authorized materials', 'desktop and mobile overflow']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
