"""Cross-role palette QA. Synthetic :8029/:8529, no model requests or real data."""
import json
import os
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get('THEME_QA_URL', 'http://127.0.0.1:8529')
OUT = Path(os.environ.get('THEME_QA_OUT', str(Path(__file__).resolve().parents[1] / 'artifacts' / 'theme-warm-ink-grape')))

def contrast(first, second):
    def luminance(value):
        parts = [float(x)/255 for x in re.findall(r'[\d.]+', value)[:3]]
        return sum(w*(v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4) for w, v in zip([.2126,.7152,.0722], parts))
    low, high = sorted([luminance(first), luminance(second)])
    return round((high+.05)/(low+.05), 2)

def main():
    OUT.mkdir(parents=True, exist_ok=True); checks = []; errors = []; ratios = []; model_calls = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        def new_page():
            ctx = browser.new_context(viewport={'width':1440,'height':1000}, reduced_motion='reduce')
            page = ctx.new_page(); page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: model_calls.append(r.url) if r.method == 'POST' and any(x in r.url for x in ['/turns','/recruiter-review','/assessments','/comparisons']) else None)
            return ctx, page
        def visit(page, role, path, width=1440):
            page.set_viewport_size({'width':width,'height':1000 if width>500 else 844})
            page.goto(BASE+path); page.wait_for_load_state('networkidle')
            dims=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
            assert dims['scroll'] <= width+1, (role,path,dims)
            checks.append([role,path,width])
        def login(phone, role):
            ctx, page = new_page(); page.goto(BASE+('/admin/login' if role=='admin' else '/login?role='+role))
            page.locator('#auth-phone').fill(phone); page.locator('#auth-password').fill('Scenario-password-2026')
            page.locator('form button.primary').click(); page.wait_for_url('**/admin' if role=='admin' else '**/workspace')
            return ctx, page
        def check_nav(page, role):
            colors = page.locator('.sidebar').evaluate("""e=>{const nav=e.querySelector('.nav-group>a:not(.router-link-active)'), active=e.querySelector('.router-link-active'), small=e.querySelector('.sidebar-foot small');
              return {bg:getComputedStyle(e).backgroundColor,fg:getComputedStyle(nav).color,muted:getComputedStyle(small).color,active:getComputedStyle(active).backgroundColor}}""")
            for key in ['fg','muted']:
                ratio=contrast(colors[key], colors['bg']); assert ratio>=4.5,(role,key,colors,ratio)
                ratios.append([role,'navigation '+key,ratio])
            assert colors['active'] != colors['bg']
        ctx,page=new_page()
        for path in ['/', '/login', '/register', '/forgot-password', '/admin/login']:
            visit(page,'public',path); page.screenshot(path=str(OUT/('public-'+path.replace('/','_')+'.png')), full_page=True)
            visit(page,'public',path,390)
        ctx.close()
        routes={
            'enterprise':['/workspace','/jobs','/resumes','/applications','/messages','/reports','/preferences','/matches','/compare','/recruiter-ai'],
            'candidate':['/workspace','/jobs','/resumes','/applications','/messages','/fit','/ai-workspace','/preferences','/matches','/compare'],
            'admin':['/admin','/admin/enterprise-reviews','/admin/accounts','/admin/jobs','/admin/resumes','/admin/events','/admin/governance'],
        }
        for role, phone in [('enterprise','13800000991'),('candidate','13800000980'),('admin','13800000993')]:
            ctx,page=login(phone,role); check_nav(page,role)
            for path in routes[role]:
                visit(page,role,path)
                for button in page.locator('button.primary:not(:disabled),a.primary').all():
                    if not button.is_visible(): continue
                    colors=button.evaluate('e=>({fg:getComputedStyle(e).color,bg:getComputedStyle(e).backgroundColor})')
                    ratio=contrast(colors['fg'],colors['bg']); assert ratio>=4.5,(role,path,colors,ratio)
                    ratios.append([role,path+' primary',ratio])
                if path=='/jobs' and role=='enterprise':
                    page.get_by_role('button',name='编辑岗位要求',exact=True).click()
                    page.screenshot(path=str(OUT/'enterprise-job-editor.png'),full_page=True)
                    page.get_by_role('button',name='取消编辑',exact=True).click()
                if path in ['/jobs','/resumes','/recruiter-ai','/ai-workspace','/admin','/admin/enterprise-reviews']:
                    page.screenshot(path=str(OUT/(role+'-'+path.replace('/','_')+'.png')),full_page=True)
                if path=='/compare':
                    disabled=page.get_by_role('button',name='导出 CSV',exact=True)
                    if disabled.count() and disabled.is_disabled():
                        style=disabled.evaluate('e=>({border:getComputedStyle(e).borderStyle,cursor:getComputedStyle(e).cursor})')
                        assert style=={'border':'dashed','cursor':'not-allowed'},style
                visit(page,role,path,390)
                if path in ['/recruiter-ai','/ai-workspace','/admin']:
                    page.screenshot(path=str(OUT/(role+'-mobile.png')),full_page=True)
            # Off-canvas navigation must remain legible when opened on a phone.
            page.locator('.navigation-toggle').click()
            expect(page.locator('.sidebar')).to_be_visible()
            check_nav(page,role)
            ctx.close()
        ctx,page=login('13800000994','candidate')
        for width in [1440,390]:visit(page,'unverified','/enterprise-verification',width)
        ctx.close(); browser.close()
    assert not errors,errors
    assert not model_calls,model_calls
    result={'checks':checks,'viewport_checks':len(checks),'contrast_ratios':ratios,'page_errors':errors,'model_requests':model_calls}
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
