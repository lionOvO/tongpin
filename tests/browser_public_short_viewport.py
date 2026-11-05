"""Regression: desktop zoom must not silently remove the scroll narrative."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = os.environ.get('PUBLIC_HOME_URL', 'http://127.0.0.1:8501')
OUT = Path('artifacts/public-home/short-viewport')
OUT.mkdir(parents=True, exist_ok=True)


def run():
    errors, writes, layouts = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
            headless=True)
        page = browser.new_page(viewport={'width': 1536, 'height': 730})
        def api(route):
            if route.request.method != 'GET':
                writes.append(route.request.url)
            route.fulfill(status=401, json={'detail': 'Login required'})
        page.route('**/api/**', api)
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(URL, wait_until='networkidle')

        def nav(index):
            page.locator('.tp-sections button').nth(index).click()
            page.wait_for_timeout(950)

        def bounds():
            return page.locator('.tp-story-stage>section:not([inert])').evaluate('''e=>{
                const selectors='.tp-hero-copy,.tp-hero-art,.tp-person-card,.tp-scene-figure,.tp-edit-demo,.tp-employer-card,.tp-journey-demo';
                return [...e.querySelectorAll(selectors)].filter(n=>n.checkVisibility()).map(n=>{
                    const r=n.getBoundingClientRect();return {name:n.className,top:r.top,bottom:r.bottom,left:r.left,right:r.right}
                })}''')

        def fits(width, height, context):
            rectangles = bounds()
            assert rectangles, context
            assert all(r['top'] >= 88 - 1 and r['bottom'] <= height - 8
                       and r['left'] >= 0 and r['right'] <= width for r in rectangles), (width, height, context, rectangles)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')

        for width, height in [(1536, 730), (1366, 700), (1280, 657), (1024, 640)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.wait_for_timeout(250)
            assert page.locator('.tp-fixed').count() == 1
            for index in range(5):
                nav(index)
                if index == 0:
                    page.wait_for_timeout(2200)
                fits(width, height, index)
                if index == 2:
                    for step in range(5):
                        page.locator('.tp-edit-steps button').nth(step).click()
                        page.wait_for_timeout(300)
                        fits(width, height, f'edit {step}')
                if index == 3:
                    for tab in range(4):
                        page.locator('.tp-employer-body>nav>button').nth(tab).click()
                        page.wait_for_timeout(200)
                        fits(width, height, f'enterprise {tab}')
                page.screenshot(path=str(OUT / f'{width}x{height}-scene-{index}.png'))
            nav(0)
            page.get_by_role('button', name='个人资料演示', exact=True).click()
            page.wait_for_timeout(2300)
            for person in range(3):
                page.locator('.tp-person-picker button').nth(person).click()
                page.wait_for_timeout(2300)
                fits(width, height, f'profile {person}')
            page.get_by_role('button', name='双向相遇', exact=True).click()
            page.wait_for_timeout(2300)
            fits(width, height, 'meeting')
            layouts.append(f'{width}x{height}: fixed, 5 scenes and manual states fit')

        # Cross the layout breakpoint in both directions, as browser zoom does.
        for height, fixed in [(639, False), (640, True), (730, True), (620, False), (700, True)]:
            page.set_viewport_size({'width': 1366, 'height': height})
            page.wait_for_timeout(300)
            assert bool(page.locator('.tp-fixed').count()) == fixed
            if fixed:
                nav(1)
                assert page.locator('.tp-story-stage>section:not([inert])').count() == 1
            else:
                assert page.locator('.tp-story-stage>section[inert]').count() == 0
                assert page.locator('.tp-story-track').evaluate('e=>e.style.height') == ''

        nav(0)
        page.wait_for_timeout(2300)
        unit = page.evaluate('Math.max(800,Math.min(1000,innerHeight*.95))')
        page.evaluate('y=>scrollTo(0,y)', unit * .66)
        page.wait_for_timeout(850)
        page.mouse.wheel(0, unit * .32)
        frames = page.evaluate('''async()=>{const samples=[];await new Promise(resolve=>{
            function sample(){samples.push(getComputedStyle(document.querySelector('.tp-transition-paper')).transform);
            if(samples.length<40)requestAnimationFrame(sample);else resolve()};requestAnimationFrame(sample)});return samples}''')
        assert len(set(frames)) >= 5
        assert abs(page.locator('.tp-story-stage').evaluate('e=>e.getBoundingClientRect().top') - 88) < 1

        page.emulate_media(reduced_motion='reduce')
        page.wait_for_timeout(300)
        assert not page.locator('.tp-fixed').count()
        assert not page.locator('.tp-story-stage>section[inert]').count()
        assert not errors and not writes, (errors, writes)
        browser.close()
    result = {'layouts': layouts, 'resize_across_breakpoint': 'passed',
              'wheel_distinct_frames': len(set(frames)), 'reduced_motion': 'passed',
              'errors': errors, 'business_writes': writes}
    (OUT / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    run()
