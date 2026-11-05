"""Opening brand illustration: real motion, responsive assets and unchanged role entry.

All business API traffic is mocked; no accounts or paid AI are used.
"""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = os.environ.get('PUBLIC_HOME_URL', 'http://127.0.0.1:8502')
OUT = Path('artifacts/public-meeting')
OUT.mkdir(parents=True, exist_ok=True)


def run():
    errors, writes, layouts = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})

        def api(route):
            if route.request.method != 'GET':
                writes.append(route.request.url)
            route.fulfill(status=401, json={'detail': 'Login required'})

        page.route('**/api/**', api)
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(URL, wait_until='networkidle')
        page.wait_for_timeout(2300)
        image = page.locator('.tp-meeting-left')
        assert image.evaluate('e=>e.complete && e.naturalWidth > 0')
        assert page.get_by_role('button', name='双向相遇', exact=True).get_attribute('aria-pressed') == 'true'
        # Replay has intermediate transforms on both image halves and the connection.
        page.get_by_role('button', name='重播相遇', exact=True).click()
        frames = page.evaluate('''async()=>{
          const frames=[]; await new Promise(resolve=>{function sample(){
            const q=s=>getComputedStyle(document.querySelector(s));
            frames.push([q('.tp-meeting-left').transform,q('.tp-meeting-right').transform,q('.tp-resonance-left').strokeDashoffset]);
            if(frames.length<90) requestAnimationFrame(sample);else resolve();
          }requestAnimationFrame(sample)});return frames;
        }''')
        assert len(set(str(f) for f in frames)) > 20
        page.wait_for_timeout(1000)
        page.screenshot(path=str(OUT / 'desktop.png'))
        # Switching changes only the visual; headings and role actions stay in place.
        heading = page.locator('#tp-title').bounding_box()
        page.get_by_role('button', name='个人资料演示', exact=True).click()
        page.wait_for_timeout(2300)
        assert page.locator('.tp-person-card').is_visible()
        assert page.locator('#tp-title').bounding_box() == heading
        page.screenshot(path=str(OUT / 'profile-view.png'))
        page.locator('.tp-person-picker button').nth(1).click()
        assert '赵启航' in page.locator('.tp-person-heading').inner_text()
        page.get_by_role('button', name='双向相遇', exact=True).click()
        # Layout at short desktop, tablet, phone and phone landscape, in both views.
        for w, h in [(1920,1080),(1440,1000),(1366,768),(1024,740),(768,1024),(390,844),(360,740),(844,390)]:
            page.set_viewport_size({'width':w,'height':h})
            page.evaluate('scrollTo(0,0)')
            page.wait_for_timeout(2300)
            for view in ['双向相遇', '个人资料演示']:
                page.get_by_role('button', name=view, exact=True).click()
                page.wait_for_timeout(2300)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (w,h,view)
                selector = '.tp-meeting' if view == '双向相遇' else '.tp-person-card'
                bounds = page.locator(selector).bounding_box()
                if page.locator('.tp-fixed').count():
                    assert bounds['y'] >= 88 and bounds['y'] + bounds['height'] <= h - 45, (w,h,view,bounds)
                if w in [390,360] and view == '双向相遇':
                    page.locator('.tp-hero-track').screenshot(path=str(OUT / f'mobile-hero-{w}.png'))
            page.get_by_role('button', name='双向相遇', exact=True).click()
            layouts.append(f'{w}x{h}: both views fit')
        # A browser may keep its already-cached desktop srcset image on resize.
        # Verify the phone's first load in a fresh document instead.
        phone = browser.new_page(viewport={'width':390,'height':844})
        phone.route('**/api/**', api)
        phone.goto(URL, wait_until='networkidle')
        assert phone.locator('.tp-meeting-right').evaluate('e=>e.complete && e.currentSrc.includes("small")')
        phone.close()
        # Actual scene handoff stays animated, with inactive content unfocusable.
        page.set_viewport_size({'width':1440,'height':1000})
        page.evaluate('scrollTo(0,0)')
        page.wait_for_timeout(2300)
        unit = 950
        samples = []
        for progress in [.68,.76,.84,.92,1]:
            page.evaluate('y=>scrollTo(0,y)',unit*progress)
            page.wait_for_timeout(850)
            samples.append(page.locator('.tp-transition-paper').evaluate('e=>getComputedStyle(e).transform'))
        assert len(set(samples)) == 5
        assert page.locator('.tp-hero-track').evaluate('e=>e.inert')
        page.emulate_media(reduced_motion='reduce')
        page.evaluate('scrollTo(0,0)')
        page.wait_for_timeout(300)
        assert not page.locator('.tp-fixed').count()
        assert image.evaluate('e=>getComputedStyle(e).animationName') == 'none'
        assert image.evaluate('e=>getComputedStyle(e).transform') == 'none'
        assert page.locator('.tp-resonance-left').evaluate('e=>getComputedStyle(e).strokeDashoffset') == '0px'
        for name, role in [('我要求职','candidate'),('我要招聘','enterprise')]:
            page.goto(URL, wait_until='networkidle')
            page.get_by_role('button', name=name, exact=True).click()
            page.wait_for_url(f'**/login?role={role}')
        assert not errors and not writes, (errors,writes)
        browser.close()
    result = {'layouts':layouts,'distinct_intro_frames':len(set(str(f) for f in frames)),
              'handoff_samples':len(set(samples)),'role_entry':'passed','reduced_motion':'passed',
              'page_errors':errors,'business_writes':writes}
    (OUT / 'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    run()
