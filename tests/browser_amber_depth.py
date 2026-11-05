"""Actual control depth, contrast and pane separation on isolated theme fixtures."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_theme_plan_one import contrast

BASE = 'http://127.0.0.1:8529'
OUT = Path(__file__).resolve().parents[1] / 'artifacts' / 'theme-amber'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []; errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        context = browser.new_context(viewport={'width':1440,'height':1000})
        page = context.new_page(); page.on('pageerror', lambda e: errors.append(str(e)))

        def appearance(control):
            return control.evaluate('''e=>{const s=getComputedStyle(e);return {bg:s.backgroundColor,fg:s.color,
              shadow:s.boxShadow,transform:s.transform,outline:s.outlineWidth,border:s.borderStyle}}''')

        def depth(control, name):
            page.mouse.move(1, 1); control.scroll_into_view_if_needed(); page.wait_for_timeout(250)
            rest = appearance(control); assert rest['shadow'] != 'none', (name,rest)
            ratio = contrast(rest['fg'],rest['bg']); assert ratio >= 4.5,(name,rest,ratio)
            control.hover(); page.wait_for_timeout(250); hover = appearance(control)
            assert hover['shadow'] != rest['shadow'],(name,rest,hover)
            page.mouse.down(); page.wait_for_timeout(250); pressed = appearance(control)
            assert pressed['shadow'] != hover['shadow'],(name,pressed,hover)
            assert pressed['transform'] != hover['transform'],(name,pressed,hover)
            # Release outside the control to exercise feedback without executing an action.
            page.mouse.move(1, 1); page.mouse.up(); page.wait_for_timeout(250)
            control.focus(); assert appearance(control)['outline']=='3px',(name,appearance(control))
            results.append({'control':name,'contrast':ratio,'rest':rest,'hover':hover,'pressed':pressed})

        page.goto(BASE,wait_until='networkidle')
        depth(page.get_by_role('button',name='我要求职',exact=True),'public primary')
        depth(page.get_by_role('button',name='我要招聘',exact=True),'public secondary')
        page.goto(BASE+'/admin/login',wait_until='networkidle')
        depth(page.locator('form button.primary'),'admin login')
        page.goto(BASE+'/login?role=candidate',wait_until='networkidle')
        depth(page.locator('form button.primary'),'candidate login')
        page.locator('#auth-phone').fill('13800000980')
        page.locator('#auth-password').fill('Scenario-password-2026')
        page.locator('form button.primary').click(); page.wait_for_url('**/workspace')
        page.goto(BASE+'/ai-workspace',wait_until='networkidle')
        page.locator('#ai-layout-mode').select_option('workbench')
        panes = page.evaluate('''()=>Object.fromEntries(['.ai-materials','.ai-chat','.ai-results'].map(s=>[s,getComputedStyle(document.querySelector(s)).backgroundColor]))''')
        assert len(set(panes.values()))==3,panes
        heading=page.locator('.ai-results>.ai-panel-heading').evaluate('e=>({bg:getComputedStyle(e).backgroundColor,fg:getComputedStyle(e).color})')
        assert contrast(heading['fg'],heading['bg'])>=4.5,heading
        page.screenshot(path=str(OUT/'candidate-workbench.png'))
        send=page.locator('.ai-send'); assert send.is_disabled()
        disabled=appearance(send); assert disabled['shadow']=='none' and disabled['border']=='dashed',disabled
        page.locator('#ai-message').fill('仅用于按钮状态检查，不发送')
        depth(send,'candidate send')
        page.locator('#ai-message').fill('')
        page.set_viewport_size({'width':390,'height':844}); page.wait_for_timeout(200)
        page.screenshot(path=str(OUT/'candidate-workbench-mobile.png'))
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.set_viewport_size({'width':1440,'height':1000})
        page.goto(BASE+'/resumes',wait_until='networkidle')
        depth(page.get_by_role('button',name='导入简历',exact=True),'resume import')
        page.emulate_media(reduced_motion='reduce')
        primary=page.get_by_role('button',name='导入简历',exact=True); primary.hover(); page.wait_for_timeout(100)
        assert appearance(primary)['transform']=='none',appearance(primary)
        results.append({'reduced_motion':'no button movement','pane_colors':panes,'disabled':disabled})
        context.close(); browser.close()
    assert not errors,errors
    (OUT/'button-depth.json').write_text(json.dumps({'checks':results,'page_errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'controls':len(results)-1,'pane_colors':panes,'page_errors':errors},ensure_ascii=False))


if __name__ == '__main__': main()
