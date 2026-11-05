"""Browser acceptance for the public story; all API traffic stays mocked.

Run from project root with .venv/Scripts/python tests/browser_public_home.py.
Uses an existing Vite server at PUBLIC_HOME_URL, default 127.0.0.1:5188.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import sync_playwright

URL = os.environ.get('PUBLIC_HOME_URL', 'http://127.0.0.1:5188')
OUT = Path('artifacts/public-home')
OUT.mkdir(parents=True, exist_ok=True)


def run():
    errors, mutations, reports = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})

        def api(route):
            if route.request.method != 'GET':
                mutations.append(route.request.url)
            route.fulfill(status=401, json={'detail': {'code': 'LOGIN_REQUIRED', 'message': '请先登录'}})

        context.route('**/api/**', api)
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.add_init_script('''
          window.storyMetrics = {shifts: 0, longTasks: []};
          new PerformanceObserver(list => { for (const e of list.getEntries())
            if (!e.hadRecentInput) window.storyMetrics.shifts += e.value;
          }).observe({type:'layout-shift', buffered:true});
          new PerformanceObserver(list => { for (const e of list.getEntries())
            window.storyMetrics.longTasks.push({start:e.startTime,duration:e.duration});
          }).observe({type:'longtask', buffered:true});
        ''')
        page.goto(URL, wait_until='networkidle')
        page.get_by_role('button', name='个人资料演示', exact=True).click()
        page.wait_for_timeout(2400)
        def scene(index):
            if page.locator('.tp-public.tp-fixed').count():
                page.locator('.tp-sections button').nth(index).click()
                page.wait_for_timeout(1400)
            else:
                page.locator(['#tp-main','#tp-connect','#tp-edit','#tp-company','#tp-journey'][index]).scroll_into_view_if_needed()
                page.wait_for_timeout(100)

        assert page.get_by_role('heading', level=1).inner_text() == '让经历被看见。\n让选择有回响。'
        assert page.locator('.tp-person-card').evaluate('el=>getComputedStyle(el).animationName') == 'none'
        page.screenshot(path=str(OUT / 'desktop-fragments.png'))
        page.evaluate('scrollTo(0,560)'); page.wait_for_timeout(750)
        assert page.locator('.tp-person-card').evaluate('el=>getComputedStyle(el).opacity') == '1'
        assert not page.locator('.tp-person-card').evaluate('el=>getComputedStyle(el).transform') != 'matrix(1, 0, 0, 1, 0, 0)'
        page.screenshot(path=str(OUT / 'desktop-hero.png'))

        # All three PDFs are represented, and the selected person stays consistent.
        for button, name, project in [('测试开发', '赵启航', '自动化测试平台'), ('产品协作', '周雨桐', '用户反馈分析平台'), ('数据分析', '吴思琪', '销售数据分析看板')]:
            page.locator('.tp-person-picker').get_by_role('button', name=button).click()
            assert name in page.locator('.tp-person-heading').inner_text()
            assert name in page.locator('.tp-employer-card>header').text_content()
            assert project in page.locator('.tp-document').text_content()
        page.wait_for_timeout(2300)
        scene(1)
        for i in range(3):
            page.locator('.tp-relation-list button').nth(i).click()
            assert page.locator('.tp-connected-pair').nth(i).get_attribute('class').endswith('active')
            page.locator('.tp-quote-panel blockquote').wait_for()
            assert page.locator('.tp-quote-panel blockquote').inner_text().strip('“”')
        selected = page.locator('.tp-relation-list button[aria-pressed=true]').inner_text()
        page.evaluate('scrollBy(0,100)')
        page.wait_for_timeout(80)
        assert page.locator('.tp-relation-list button[aria-pressed=true]').inner_text() == selected
        page.screenshot(path=str(OUT / 'desktop-connection.png'))

        # Pause is real, manual choices persist, and adoption updates the preview.
        scene(2)
        page.get_by_role('button', name='暂停演示', exact=True).click()
        page.locator('.tp-edit-steps button').nth(0).click()
        page.wait_for_timeout(6700)
        page.wait_for_timeout(450)
        assert page.locator('.tp-edit-stage').get_attribute('data-step') == '0'
        page.get_by_role('button', name='播放演示', exact=True).click()
        page.wait_for_timeout(6800)
        assert page.locator('.tp-edit-stage').get_attribute('data-step') == '1'
        scene(3)
        page.wait_for_timeout(6700)
        assert page.locator('.tp-edit-stage').get_attribute('data-step') == '1'
        scene(2)
        page.locator('.tp-edit-steps button').nth(2).click()
        page.wait_for_timeout(450)
        assert '修改前' in page.locator('.tp-edit-stage').inner_text()
        page.screenshot(path=str(OUT / 'desktop-edit-comparison.png'))
        page.get_by_role('button', name='下一步修改演示').click()
        page.wait_for_timeout(450)
        page.get_by_role('button', name='采纳这版表达（演示）').click()
        page.wait_for_timeout(450)
        assert 'updated' in page.locator('.tp-selected-text').get_attribute('class')
        assert '围绕收入与转化趋势' in page.locator('.tp-selected-text').inner_text()

        scene(3)
        for i in range(4):
            page.locator('.tp-employer-body>nav>button').nth(i).click()
            page.locator('.tp-strength-items>button').nth(1).click()
            assert '搭建销售指标看板' in page.locator('.tp-employer-source').inner_text()
        assert '如何定义' in page.locator('.tp-strength-items').inner_text()
        page.screenshot(path=str(OUT / 'desktop-employer.png'))

        scene(4)
        page.locator('.tp-journey-track button').nth(0).click()
        journey_scroll = page.evaluate('scrollY')
        for label in ['演示：主动投递', '演示：发出沟通邀请', '演示：接受邀请']:
            page.get_by_role('button', name=label, exact=True).click()
        page.locator('.tp-chat-demo').wait_for(state='visible')
        assert abs(page.evaluate('scrollY') - journey_scroll) < 2
        assert '业务数据分析师' in page.locator('.tp-shared-context').inner_text()
        page.get_by_label('试写一条演示消息').fill('想了解团队怎样使用分析看板。')
        page.get_by_role('button', name='发送演示消息', exact=True).click()
        assert '想了解团队怎样使用分析看板。' in page.locator('.tp-chat-demo').inner_text()
        assert not mutations, mutations
        page.screenshot(path=str(OUT / 'desktop-conversation.png'))

        # Measure frame intervals during native document scrolling after warm-up.
        perf = page.evaluate('''async () => {
          const intervals=[], start=performance.now(); let last=start;
          const max=document.documentElement.scrollHeight-innerHeight;
          await new Promise(resolve=>{let n=0; function tick(now){
            if(n>0) intervals.push(now-last); last=now;
            scrollTo(0, max*(1-Math.cos(n/150*Math.PI*2))/2);
            if(++n<=150) requestAnimationFrame(tick); else resolve();
          } requestAnimationFrame(tick)});
          intervals.sort((a,b)=>a-b);
          return {frames:intervals.length,p95_ms:intervals[Math.floor(intervals.length*.95)],
            max_ms:Math.max(...intervals),layout_shift:window.storyMetrics.shifts,
            scroll_long_tasks:window.storyMetrics.longTasks.filter(t=>t.start>=start)};
        }''')
        assert perf['layout_shift'] < .01, perf
        reports.append({'viewport': '1440x1000', 'performance': perf})

        # Recheck narrow, tablet, short desktop and mobile landscape layouts in all scenes.
        for width, height in [(1280, 800), (768, 1024), (390, 844), (360, 740), (844, 390)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.wait_for_timeout(100)
            for index, section in enumerate(['tp-main', 'tp-connect', 'tp-edit', 'tp-company', 'tp-journey']):
                scene(index)
                page.wait_for_timeout(60)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, section)
            if width in [390, 360]:
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(OUT / f'mobile-{width}-hero.png'))
                page.screenshot(path=str(OUT / f'mobile-{width}-full.png'), full_page=True)
                scene(2)
                page.locator('.tp-edit-steps button').nth(2).click()
                page.screenshot(path=str(OUT / f'mobile-{width}-edit.png'))
            reports.append({'viewport': f'{width}x{height}', 'horizontal_overflow': False})

        page.emulate_media(reduced_motion='reduce')
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.evaluate('scrollTo(0,0)')
        page.get_by_role('button', name='重新整理', exact=True).click()
        assert page.locator('.tp-person-card').evaluate('el=>getComputedStyle(el).animationName') == 'none'
        assert page.locator('.tp-fragments').evaluate('el=>getComputedStyle(el).display') == 'none'
        scene(2)
        assert page.get_by_role('button', name='已减少动态效果', exact=True).is_disabled()
        page.locator('.tp-edit-steps button').nth(0).click()
        page.wait_for_timeout(6700)
        page.wait_for_timeout(450)
        assert page.locator('.tp-edit-stage').get_attribute('data-step') == '0'
        page.locator('.tp-edit-steps button').nth(4).click()
        assert page.locator('.tp-selected-text.updated').is_visible()
        reports.append({'reduced_motion': 'no assembly, no autoplay, manual steps available'})

        # Both public entry buttons preserve the existing login role parameter.
        for name, role in [('我要求职', 'candidate'), ('我要招聘', 'enterprise')]:
            page.goto(URL, wait_until='networkidle')
            page.get_by_role('button', name=name, exact=True).click()
            page.wait_for_url('**/login?role=' + role)
            assert parse_qs(urlsplit(page.url).query)['role'] == [role]
        page.goto(URL, wait_until='networkidle')
        page.keyboard.press('Tab')
        assert page.locator('.tp-skip').evaluate('el=>el===document.activeElement')
        page.keyboard.press('Enter')
        assert page.url.endswith('#tp-main')
        assert not mutations and not errors, {'mutations': mutations, 'errors': errors}
        browser.close()
    result = {'cases': reports, 'example_business_write_requests': mutations, 'page_errors': errors,
              'people': 3, 'evidence_links': 3, 'editor_steps': 5, 'employer_views': 4,
              'two_way_flow_and_demo_chat': 'passed', 'anonymous_role_entry': 'passed'}
    (OUT / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    run()
