"""Two ordinary tabs sharing a browser cookie jar, real WebRTC and fake devices.

Run serve_video_preview.py plus Vite on 8515 proxied to 8025 first.
No API/WebRTC mocks on the successful call path; only device-denial is injected.
"""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

URL = os.environ.get('VIDEO_QA_URL', 'http://127.0.0.1:8515')
OUT = Path('artifacts/video-call-qa')
OUT.mkdir(parents=True, exist_ok=True)
BOOTSTRAP = json.loads((OUT / 'latest.json').read_text(encoding='utf8'))
APP_ID = BOOTSTRAP['application_id']
BROWSER = os.environ.get('VIDEO_QA_BROWSER', r'C:\Users\86185\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe')
SCRIPT = '''(() => {
  window.__qaStreams=[];window.__denyDevice=false;window.__delayDevice=false;
  if(!navigator.mediaDevices?.getUserMedia)return;
  const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia=async constraints=>{
    if(window.__denyDevice)throw new DOMException('Test denied','NotAllowedError');
    const stream=await original(constraints);window.__qaStreams.push(stream);
    if(window.__delayDevice)await new Promise(resolve=>window.__releaseDevice=resolve);
    return stream;
  };
})()'''


def run():
    errors, result, requests = [], {}, []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=BROWSER, headless=True,
            args=['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required'])
        a_context = browser.new_context(permissions=['camera', 'microphone'], viewport={'width': 1440, 'height': 960})
        b_context = a_context  # Deliberately share cookies: user identities must remain isolated.
        a_context.add_init_script(SCRIPT)
        a, b = a_context.new_page(), a_context.new_page()
        pages = [a, b]
        def login(page, phone):
            page.goto(URL + '/login?role=' + ('enterprise' if phone.endswith('651') else 'candidate'), wait_until='networkidle')
            page.locator('input[name="phone"]').fill(phone)
            page.locator('input[name="password"]').fill('Scenario-password-2026')
            page.get_by_role('button', name='登录工作空间', exact=True).click()
            expect(page.locator('.topbar-actions .account-name')).to_be_visible()
        def identity(page):
            return page.evaluate("async()=>{const m=await import('/src/store.ts');return {id:m.state.user?.id,role:m.state.user?.role,tab:m.sessionHeaders()['X-Session-Tab']}}")
        for page, phone in [(a, '13800000651'), (b, '13800000652')]:
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('response', lambda response, index=pages.index(page): requests.append({'page': index, 'url': response.url, 'status': response.status}) if '/api/video-calls' in response.url else None)
            login(page, phone)
        original_a, original_b = identity(a), identity(b)
        assert original_a['id'] != original_b['id'] and original_a['tab'] != original_b['tab']
        for page, expected in [(a, original_a), (b, original_b)]:
            page.reload(wait_until='networkidle')
            assert identity(page) == expected
        fresh = a_context.new_page()
        fresh.goto(URL + '/resumes', wait_until='networkidle')
        expect(fresh.locator('input[name="phone"]')).to_be_visible()
        fresh.close()
        b.get_by_role('button', name='退出登录', exact=True).click()
        expect(b.locator('input[name="phone"]')).to_be_visible()
        a.reload(wait_until='networkidle'); assert identity(a) == original_a
        login(b, '13800000652')
        for page in pages:
            page.goto(URL + '/messages?application=' + APP_ID, wait_until='networkidle')
            expect(page.get_by_role('button', name='发起视频通话', exact=True)).to_be_enabled()
        assert identity(a) == original_a
        def prepare(page):
            page.get_by_role('button', name='发起视频通话', exact=True).click()
            expect(page.get_by_role('button', name='开启设备并呼叫', exact=True)).to_be_visible()
        def dial(page):
            prepare(page); page.get_by_role('button', name='开启设备并呼叫', exact=True).click()
            expect(page.locator('#video-call-status')).to_contain_text('等待对方接听', timeout=15000)
        def connect(caller, receiver):
            dial(caller)
            expect(receiver.get_by_role('button', name='接听视频', exact=True)).to_be_visible(timeout=10000)
            receiver.get_by_role('button', name='接听视频', exact=True).click()
            for page in [caller, receiver]:
                expect(page.locator('#video-call-status')).to_contain_text('正在通话', timeout=30000)
                page.wait_for_function("()=>{const v=document.querySelector('.video-call-remote');return v && v.videoWidth>0 && v.readyState>=2 && v.getVideoPlaybackQuality().totalVideoFrames>5}", timeout=15000)
        def stopped(page):
            return page.evaluate('window.__qaStreams.every(s=>s.getTracks().every(t=>t.readyState==="ended"))')
        def done(page):
            expect(page.get_by_role('button', name='完成', exact=True)).to_be_visible(timeout=12000)
            assert stopped(page)
            page.get_by_role('button', name='完成', exact=True).click()
        try:
            # Opening/cancelling a preflight never activates hardware or calls anyone.
            prepare(a)
            assert a.evaluate('window.__qaStreams.length') == 0
            a.screenshot(path=str(OUT / 'desktop-preflight.png'))
            a.get_by_role('button', name='取消', exact=True).click()
            assert not a.locator('.video-call-dialog').count()
            # Browser-denied devices are actionable; no phantom call is created.
            a.evaluate('window.__denyDevice=true'); prepare(a)
            a.get_by_role('button', name='开启设备并呼叫', exact=True).click()
            expect(a.locator('.video-call-error')).to_contain_text('权限未开启')
            assert not b.locator('.video-call-dialog').count()
            a.get_by_role('button', name='取消', exact=True).click(); a.evaluate('window.__denyDevice=false')
            # A camera permission promise can resolve after cancel; all late tracks stop.
            a.evaluate('window.__delayDevice=true'); prepare(a)
            a.get_by_role('button', name='开启设备并呼叫', exact=True).click()
            a.wait_for_function('typeof window.__releaseDevice==="function"')
            a.get_by_role('button', name='取消', exact=True).click()
            a.evaluate('window.__releaseDevice();window.__delayDevice=false')
            a.wait_for_function('window.__qaStreams.every(s=>s.getTracks().every(t=>t.readyState==="ended"))')
            # Actual video decoding in both browsers, then device controls and minimized navigation.
            connect(a, b)
            decoded = [page.locator('.video-call-remote').evaluate('v=>({width:v.videoWidth,height:v.videoHeight,frames:v.getVideoPlaybackQuality().totalVideoFrames})') for page in [a, b]]
            a.screenshot(path=str(OUT / 'desktop-connected.png'))
            a.get_by_role('button', name='关闭麦克风', exact=True).click()
            assert a.evaluate('window.__qaStreams.at(-1).getAudioTracks().every(t=>!t.enabled)')
            a.get_by_role('button', name='关闭摄像头', exact=True).click()
            assert a.evaluate('window.__qaStreams.at(-1).getVideoTracks().every(t=>!t.enabled)')
            a.get_by_role('button', name='开启麦克风', exact=True).click()
            a.get_by_role('button', name='开启摄像头', exact=True).click()
            a.get_by_role('button', name='查看沟通资料', exact=True).click()
            expect(a.locator('.video-call-dock')).to_be_visible()
            a.locator('nav a[href="/workspace"]').click()
            expect(a.locator('.video-call-dock')).to_be_visible()
            assert not stopped(a)
            a.locator('.video-call-dock').click()
            # Interrupt signaling only; browser-wide offline also forcibly closes RTC.
            a_context.route('**/api/video-calls/**', lambda route: route.abort('internetdisconnected'))
            expect(a.locator('.video-call-network')).to_be_visible(timeout=15000)
            a_context.unroute('**/api/video-calls/**')
            expect(a.locator('.video-call-network')).to_be_hidden(timeout=15000)
            expect(a.locator('#video-call-status')).to_contain_text('正在通话')
            # Phone layout keeps all controls visible and the call alive.
            b.set_viewport_size({'width': 390, 'height': 844})
            b.screenshot(path=str(OUT / 'mobile-connected.png'))
            rect = b.locator('.video-call-dialog').bounding_box()
            assert rect and rect['x'] >= 0 and rect['x'] + rect['width'] <= 390
            expect(b.get_by_role('button', name='结束通话', exact=True)).to_be_in_viewport()
            b.get_by_role('button', name='结束通话', exact=True).click()
            done(b); done(a)
            b.set_viewport_size({'width': 1440, 'height': 960})
            a.goto(URL + '/messages?application=' + APP_ID, wait_until='networkidle')
            expect(a.get_by_label('视频通话记录')).to_contain_text('通话已结束', timeout=10000)
            # Caller cancellation and receiver declining require no receiver media.
            receiver_streams = b.evaluate('window.__qaStreams.length')
            dial(a)
            expect(b.get_by_role('button', name='接听视频', exact=True)).to_be_visible(timeout=10000)
            a.get_by_role('button', name='取消呼叫', exact=True).click()
            done(a); done(b)
            assert b.evaluate('window.__qaStreams.length') == receiver_streams
            dial(a)
            expect(b.get_by_role('button', name='婉拒', exact=True)).to_be_visible(timeout=10000)
            b.get_by_role('button', name='婉拒', exact=True).click()
            done(b); done(a)
            assert b.evaluate('window.__qaStreams.length') == receiver_streams
            # Role symmetry: candidate can call; one tab answers, the second cannot hijack.
            second_a = a_context.new_page(); pages.append(second_a)
            second_a.on('pageerror', lambda e: errors.append(str(e)))
            login(second_a, '13800000651')
            second_a.goto(URL + '/messages?application=' + APP_ID, wait_until='networkidle')
            connect(b, a)
            expect(second_a.locator('.video-call-dock')).to_contain_text('另一个窗口', timeout=10000)
            second_a.locator('.video-call-dock').click()
            expect(second_a.get_by_role('button', name='接听视频', exact=True)).to_have_count(0)
            assert second_a.evaluate('window.__qaStreams.length') == 0
            second_a.close()
            # Leaving a live page sends keepalive termination, and peer devices stop too.
            b.goto('about:blank')
            done(a)
            result = {'same_cookie_jar_two_accounts_refresh_logout_fresh_tab': 'passed', 'real_remote_decoding': decoded, 'permission_denial_and_late_release': 'passed',
                      'mute_camera_minimize_navigation': 'passed', 'signaling_network_recovery': 'passed',
                      'mobile': '390x844 controls visible', 'cancel_decline_no_remote_devices': 'passed',
                      'reverse_direction_and_multi_tab': 'passed', 'pagehide_releases_both': 'passed', 'errors': errors}
            assert not errors, errors
        except Exception:
            (OUT / 'failure-requests.json').write_text(json.dumps(requests, indent=2), encoding='utf8')
            for index, page in enumerate(pages):
                if not page.is_closed():
                    page.screenshot(path=str(OUT / f'failure-{index}.png'))
                    print(index, page.evaluate('''async()=>({error:document.querySelector('.video-call-error')?.textContent,
                      streams:window.__qaStreams?.map(s=>s.getTracks().map(t=>({kind:t.kind,state:t.readyState}))),
                      devices:await navigator.mediaDevices?.enumerateDevices()})'''), flush=True)
                    if page.url.startswith(URL):
                        print('state', index, page.evaluate("async()=>{const m=await import('/src/video-calls.ts');const s=await import('/src/store.ts');return {call:m.videoCall,user:s.state.user?.role,scope:s.state.sessionScope}}"), flush=True)
            raise
        finally:
            browser.close()
    (OUT / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    run()
