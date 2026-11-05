"""Staff entry animation and unchanged authentication flow, synthetic API only."""
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

OUT = Path(__file__).resolve().parents[1] / 'artifacts' / 'admin-entry'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    errors, writes, checks = [], [], []
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda e:errors.append(str(e)))
        signed_in=False
        session={'user':{'id':'synthetic-staff','actor':'admin:synthetic','role':'admin','name':'合成测试工作人员','session_scope':'admin','has_password':True},'csrf_token':'mock'}
        def api(route):
            nonlocal signed_in
            path=urlparse(route.request.url).path.removeprefix('/api')
            if route.request.method != 'GET': writes.append(path)
            if path=='/auth/admin/me':
                if not signed_in:
                    route.fulfill(status=401,json={'detail':{'code':'AUTH_REQUIRED','message':'请登录'}});return
                data=session
            elif path=='/auth/options':data={'sms_available':True,'missing':[]}
            elif path=='/auth/admin/login/password':
                body=route.request.post_data_json
                assert set(body)=={'phone','password'}
                assert body['phone']=='13800000001'
                signed_in=True;data=session
            elif path=='/config/presentation':data={'tier_labels':{},'banned_terms':[],'enterprise_banned_terms':[]}
            elif path=='/health':data={'status':'ok','llm_mode':'demo','env':'demo'}
            elif path=='/admin/overview':data={'pending_verifications':0,'accounts':0,'job_profiles':0,'resumes':0}
            elif path.startswith('/messages/'):data={'items':[],'total':0,'unread_total':0}
            else:data=[]
            route.fulfill(status=200,json=data)
        page.route('**/api/**',api)
        page.goto('http://127.0.0.1:8502/admin/login?redirect=/admin',wait_until='networkidle')
        expect(page.locator('.admin-entry-story')).to_be_visible()
        page.wait_for_timeout(1700)
        page.screenshot(path=str(OUT/'entry-1440.png'),full_page=True)
        # Actual timed playback, then manual selection must stop the timer.
        expect(page.locator('.admin-entry-scene-buttons button').nth(1)).to_have_attribute('aria-pressed','true',timeout=8000)
        page.locator('.admin-entry-scene-buttons button').nth(2).click()
        expect(page.get_by_role('button',name='播放流程演示',exact=True)).to_be_visible()
        page.wait_for_timeout(6800)
        expect(page.locator('.admin-entry-scene-buttons button').nth(2)).to_have_attribute('aria-pressed','true')
        before=page.locator('.auth-card').bounding_box()
        page.locator('.admin-entry-scene-buttons button').nth(0).click();page.wait_for_timeout(800)
        after=page.locator('.auth-card').bounding_box()
        assert abs(before['x']-after['x'])<1 and abs(before['y']-after['y'])<1
        page.get_by_role('button',name='播放流程演示',exact=True).click()
        page.locator('#auth-phone').focus()
        expect(page.get_by_role('button',name='播放流程演示',exact=True)).to_be_visible()
        checks.append('autoplay, manual selection and pause, form focus pauses, form does not move')
        for width,height in [(1920,1080),(1440,1000),(1024,768),(768,1024),(390,844),(360,740)]:
            page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(200)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            if width<900: assert page.locator('.auth-card').bounding_box()['y']<150
            if width in [390,360]: page.screenshot(path=str(OUT/f'entry-{width}.png'),full_page=True)
            checks.append(f'layout {width}x{height}')
        page.set_viewport_size({'width':1440,'height':1000})
        page.emulate_media(reduced_motion='reduce')
        expect(page.locator('.admin-entry-fragments')).not_to_be_visible()
        expect(page.locator('.admin-entry-play')).to_have_count(0)
        page.locator('.admin-entry-scene-buttons button').nth(1).click()
        expect(page.locator('.admin-entry-scene')).to_have_attribute('aria-label','资料边界')
        checks.append('reduced motion stops assembly and autoplay; manual switching remains')
        page.get_by_role('button',name='验证码登录',exact=True).click()
        expect(page.locator('#auth-code')).to_be_visible()
        expect(page.locator('#auth-password')).not_to_be_visible()
        page.get_by_role('button',name='密码登录',exact=True).click()
        page.get_by_role('button',name='登录管理端',exact=True).click()
        expect(page.locator('.feedback.error')).to_contain_text('请填写登录手机号')
        assert not writes
        page.locator('#auth-phone').fill('13800000001')
        page.locator('#auth-password').fill('Synthetic-password-2026')
        page.get_by_role('button',name='登录管理端',exact=True).click()
        page.wait_for_url('**/admin')
        expect(page.locator('.admin-stats')).to_be_visible()
        expect(page.locator('.admin-stat')).to_have_count(4)
        expect(page.locator('.admin-workflow')).to_be_visible()
        expect(page.locator('.admin-story-track')).to_have_count(0)
        expect(page.locator('.admin-overview')).to_have_count(0)
        page.screenshot(path=str(OUT/'restored-overview-1440.png'),full_page=True)
        assert writes==['/auth/admin/login/password'],writes
        checks.append('validation, password/SMS switch, dedicated staff login endpoint and restored static overview')
        assert not errors,errors
        browser.close()
    report={'checks':checks,'page_errors':errors,'mocked_writes':writes,'live_writes':0}
    (OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
