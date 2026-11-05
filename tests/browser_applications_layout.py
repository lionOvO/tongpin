"""Real-browser layout and workflow checks against the isolated recruiter preview.

Run serve_recruiter_preview.py on 8019 and Vite on 8519 with that API proxy.
Only synthetic QA accounts are changed. Model responses use the preview fixture.
"""
import json
import os
import traceback
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

URL = os.environ.get('APPLICATIONS_QA_URL', 'http://127.0.0.1:8519')
OUT = Path('artifacts/applications-layout-qa')
OUT.mkdir(parents=True, exist_ok=True)
BROWSER = r'C:\Users\86185\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe'


def run():
    expect.set_options(timeout=20000)
    checks, errors, writes = {}, [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=BROWSER, headless=True, args=['--disable-gpu'])
        context = browser.new_context(viewport={'width': 1920, 'height': 1080}, device_scale_factor=1)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: writes.append(request.url) if request.method == 'POST' and 'recruiter-review' in request.url else None)

        def login(target, phone, role):
            target.goto(URL + '/login?role=' + role, wait_until='networkidle')
            target.locator('input[name="phone"]').fill(phone)
            target.locator('input[name="password"]').fill('Scenario-password-2026')
            target.get_by_role('button', name='登录工作空间', exact=True).click()
            expect(target.locator('.topbar-actions .account-name')).to_be_visible()

        def select(name):
            page.locator('.application-candidate-row').filter(has_text=name).click()
            expect(page.locator('.dossier-identity h2')).to_contain_text(name)
            expect(page.get_by_role('tab', name='资料概览', exact=True)).to_have_attribute('aria-selected', 'true')

        def tab(name):
            page.get_by_role('tab', name=name).click()

        def no_overflow(target):
            assert target.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')

        try:
            login(page, '13800000991', 'enterprise')
            page.goto(URL + '/applications', wait_until='networkidle')
            expect(page.locator('.application-candidate-row')).to_have_count(3)
            select('陈予安')
            expect(page.get_by_role('button', name='更新资料卡', exact=True)).to_be_visible()
            expect(page.get_by_role('link', name='进入沟通', exact=False).first).to_be_visible()
            expect(page.locator('.profile-options')).to_have_count(0)
            assert not writes, 'Simply reading a dossier must not trigger model generation'
            checks['existing_card_and_actions'] = True
            no_overflow(page)
            page.screenshot(path=str(OUT / 'desktop-1920.png'), full_page=True)

            tab('简历与岗位')
            expect(page.locator('.dossier-document').first).to_contain_text('增加重复提交的幂等校验')
            expect(page.locator('.dossier-job-document')).to_contain_text('FastAPI')
            tab('双方期待')
            expect(page.get_by_role('heading', name='等待双方共享期待')).to_be_visible()
            tab('进展记录')
            expect(page.locator('.dossier-timeline')).to_contain_text('接受')
            history = page.get_by_role('tab', name='进展记录')
            history.focus(); history.press('Home')
            expect(page.get_by_role('tab', name='资料概览', exact=True)).to_be_focused()
            page.keyboard.press('ArrowRight')
            expect(page.get_by_role('tab', name='简历与岗位')).to_be_focused()
            checks['tabs_keyboard_materials_history_expectations'] = True

            with page.expect_download() as downloading:
                page.get_by_role('button', name='下载投递简历（TXT）', exact=True).click()
            download = downloading.value
            download.save_as(str(OUT / 'synthetic-resume.txt'))
            assert 'FastAPI' in (OUT / 'synthetic-resume.txt').read_text(encoding='utf-8-sig')
            page.get_by_role('button', name='一键导入简历库', exact=True).click()
            expect(page.get_by_role('button', name='已导入简历库', exact=True)).to_be_disabled()
            checks['download_and_import'] = True

            select('林知夏')
            expect(page.get_by_role('button', name='生成资料卡', exact=True)).to_be_enabled()
            expect(page.locator('.profile-options')).to_have_count(0)
            page.get_by_role('button', name='分析设置', exact=True).click()
            expect(page.locator('.profile-options')).to_be_visible()
            page.get_by_role('button', name='分析设置', exact=True).click()
            page.get_by_role('button', name='生成资料卡', exact=True).click()
            expect(page.get_by_role('button', name='更新资料卡', exact=True)).to_be_visible(timeout=15000)
            assert len(writes) == 1
            checks['manual_ai_generation_and_settings'] = True

            for width, height, name in [(1440, 900, 'desktop-1440'), (1280, 800, 'laptop-1280'), (390, 844, 'mobile-390')]:
                page.set_viewport_size({'width': width, 'height': height})
                if width < 761:
                    page.wait_for_function("getComputedStyle(document.querySelector('.sidebar')).visibility === 'hidden' && document.querySelector('.application-dossier').getBoundingClientRect().width > 320")
                else:
                    page.wait_for_function("document.querySelector('.main-shell').getBoundingClientRect().width > 800")
                page.evaluate('scrollTo(0, 0)')
                no_overflow(page)
                page.screenshot(path=str(OUT / (name + '.png')), full_page=True)
            checks['responsive_no_horizontal_overflow'] = True

            page.set_viewport_size({'width': 1440, 'height': 900})
            select('周启明')
            page.get_by_role('button', name='邀请沟通', exact=True).click()
            dialog = page.get_by_role('dialog')
            expect(dialog).to_be_visible()
            dialog.locator('textarea').fill('希望进一步了解你核对数据口径的项目经历，可商量一次线上沟通。')
            dialog.get_by_role('button', name='邀请沟通', exact=True).click()
            expect(dialog).to_have_count(0)
            expect(page.locator('.dossier-heading-actions > .pill')).to_contain_text('邀请')
            expect(page.locator('.dossier-invitation')).to_contain_text('核对数据口径')
            tab('进展记录')
            expect(page.locator('.dossier-timeline')).to_contain_text('核对数据口径')
            checks['real_invitation_and_timeline'] = True

            page.get_by_role('searchbox', name='搜索投递').fill('不存在的候选人')
            expect(page.locator('.application-candidate-row')).to_have_count(0)
            expect(page.locator('.application-dossier')).to_have_count(0)
            page.get_by_role('button', name='清除筛选', exact=True).click()
            expect(page.locator('.application-candidate-row')).to_have_count(3)
            expect(page.locator('.application-dossier')).to_be_visible()
            page.get_by_role('combobox', name='筛选进展').select_option('accepted')
            expect(page.locator('.application-candidate-row')).to_have_count(1)
            expect(page.locator('.dossier-identity h2')).to_contain_text('陈予安')
            page.get_by_role('combobox', name='筛选进展').select_option('all')
            expect(page.locator('.application-candidate-row')).to_have_count(3)
            checks['filtering_and_selection'] = True

            candidate = context.new_page()
            candidate.on('pageerror', lambda error: errors.append(str(error)))
            login(candidate, '13800000980', 'candidate')
            candidate.goto(URL + '/applications', wait_until='networkidle')
            expect(candidate.get_by_role('heading', name='我的投递', exact=True)).to_be_visible()
            expect(candidate.locator('.hiring-resume').first).to_contain_text('陈予安')
            expect(candidate.get_by_role('link', name='进入消息中心', exact=True)).to_be_visible()
            expect(page.locator('.topbar-actions .account-name')).to_contain_text('991')
            checks['candidate_view_and_tab_isolation_preserved'] = True

            select('林知夏')
            page.locator('.dossier-other-actions summary').click()
            page.get_by_role('button', name='暂不推进这份投递', exact=True).click()
            page.get_by_role('dialog').get_by_role('button', name='暂不推进这份投递', exact=True).click()
            expect(page.get_by_role('dialog')).to_have_count(0)
            expect(page.locator('.recruiter-profile')).to_have_count(0)
            expect(page.locator('.application-resume-tools')).to_have_count(0)
            tab('简历与岗位')
            expect(page.locator('.dossier-document').first).to_contain_text('授权暂不可用')
            checks['ended_authorization_preserved'] = True

            assert not errors, errors
            (OUT / 'verification.json').write_text(json.dumps({'checks': checks, 'page_errors': errors, 'model_generations': len(writes)}, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(checks, ensure_ascii=False))
        except Exception:
            traceback.print_exc()
            try:
                page.screenshot(path=str(OUT / 'failure.png'), full_page=True)
                (OUT / 'failure.html').write_text(page.content(), encoding='utf-8')
            except Exception:
                pass
            raise
        finally:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == '__main__':
    run()
