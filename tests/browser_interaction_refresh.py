"""Cross-role visual QA with synthetic-only fixture at ports 8019/8519."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts'/'interaction-refresh'
BASE='http://127.0.0.1:8519'
PW='Scenario-password-2026'


def main():
 OUT.mkdir(parents=True,exist_ok=True)
 checks=[];errors=[];overflows=[]
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
  def login(phone,role):
   context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
   page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(BASE+('/admin/login' if role=='admin' else '/login?role='+role))
   page.locator('#auth-phone').fill(phone);page.locator('#auth-password').fill(PW)
   page.locator('form button.primary').click();page.wait_for_url('**/admin' if role=='admin' else '**/workspace')
   return context,page
  def visit(page,role,path,width=1440):
   page.set_viewport_size({'width':width,'height':1000 if width>500 else 844})
   page.goto(BASE+path);page.wait_for_load_state('networkidle');page.wait_for_timeout(120)
   actual=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
   if actual['scroll']>actual['width']+1:
    details=page.evaluate('''[...document.querySelectorAll('body *')].filter(e=>{let r=e.getBoundingClientRect();return r.width>0&&r.right>innerWidth+1}).map(e=>({tag:e.tagName,c:e.className,w:e.getBoundingClientRect().width})).slice(-15)''')
    overflows.append({'role':role,'path':path,**actual,'elements':details})
   checks.append([role,path,width])
   return page
  ctx,page=login('13800000991','enterprise')
  visit(page,'enterprise','/jobs')
  page.locator('.job-profile-saved').wait_for()
  assert page.locator('.job-profile-editor').count()==0
  assert page.locator('.detail-metadata a,.detail-metadata button').count()==0
  state_styles=page.locator('.job-publication-actions .secondary').first.evaluate('(e)=>{let s=getComputedStyle(e);return {border:s.borderStyle,background:s.backgroundColor,cursor:s.cursor}}')
  assert state_styles['border']=='solid' and state_styles['cursor']=='pointer',state_styles
  page.screenshot(path=str(OUT/'jobs-overview.jpg'),full_page=True)
  original=page.locator('.job-facts dd').first.inner_text()
  page.get_by_role('button',name='编辑岗位要求',exact=True).click()
  page.locator('.job-profile-editor input').first.fill('未保存的界面测试')
  page.screenshot(path=str(OUT/'jobs-editor.jpg'),full_page=True)
  page.get_by_role('button',name='取消编辑',exact=True).click()
  assert page.locator('.job-facts dd').first.inner_text()==original
  page.get_by_role('button',name='编辑岗位要求',exact=True).click()
  assert page.locator('.job-profile-editor input').first.input_value()==original
  # Saving the existing values validates the new edit/read transition without altering requirements.
  page.get_by_role('button',name='确认并保存画像',exact=True).click()
  page.locator('.job-profile-saved').wait_for()
  assert page.locator('.job-facts dd').first.inner_text()==original
  page.get_by_role('tab',name='澄清用人需求',exact=True).click()
  page.screenshot(path=str(OUT/'jobs-needs.jpg'),full_page=True)
  for path in ['/workspace','/jobs','/resumes','/applications','/messages','/reports','/preferences','/matches','/compare','/recruiter-ai']:
   visit(page,'enterprise',path)
   if path=='/resumes':
    delete=page.locator('.resume-delete-link').first
    assert delete.evaluate('(e)=>getComputedStyle(e).color')=='rgb(170, 56, 70)'
    generate=page.get_by_role('button',name='生成能力报告',exact=True)
    assert generate.is_disabled()
    disabled_paper=generate.evaluate('(e)=>getComputedStyle(e).backgroundColor')
    page.locator('.resume-row input[type=checkbox]').first.check()
    assert generate.is_enabled()
    assert generate.evaluate('(e)=>getComputedStyle(e).backgroundColor')!=disabled_paper
    page.get_by_role('button',name='取消选择',exact=True).click()
   if path in ['/resumes','/reports','/preferences','/recruiter-ai']:
    page.screenshot(path=str(OUT/('enterprise-'+path[1:]+'.jpg')),full_page=True)
   visit(page,'enterprise',path,390)
  # An actual disabled export control must retain a distinct gray dashed treatment.
  visit(page,'enterprise','/compare')
  export=page.get_by_role('button',name='导出 CSV',exact=True)
  assert export.is_disabled()
  disabled_style=export.evaluate('(e)=>{let s=getComputedStyle(e);return {border:s.borderStyle,background:s.backgroundColor,cursor:s.cursor,opacity:s.opacity}}')
  assert disabled_style['border']=='dashed' and disabled_style['cursor']=='not-allowed',disabled_style
  ctx.close()
  ctx,page=login('13800000980','candidate')
  for path in ['/workspace','/jobs','/resumes','/applications','/messages','/fit','/ai-workspace','/preferences','/matches','/compare']:
   visit(page,'candidate',path)
   if path in ['/ai-workspace','/compare']:
    page.screenshot(path=str(OUT/('candidate-'+path[1:]+'.jpg')),full_page=True)
   visit(page,'candidate',path,390)
   if path=='/jobs':page.screenshot(path=str(OUT/'jobs-mobile.jpg'),full_page=True)
  # Test keyboard focus on explicit action, rather than visual hover only.
  visit(page,'candidate','/jobs');button=page.locator('.job-detail-panel button').first
  button.focus();focus=button.evaluate('(e)=>getComputedStyle(e).outlineWidth')
  assert focus=='3px',focus
  ctx.close()
  ctx,page=login('13800000994','candidate')
  visit(page,'unverified','/enterprise-verification')
  assert page.locator('.verification-group').count()==2
  page.screenshot(path=str(OUT/'verification.jpg'),full_page=True)
  visit(page,'unverified','/enterprise-verification',390)
  ctx.close()
  ctx,page=login('13800000993','admin')
  for path in ['/admin','/admin/enterprise-reviews','/admin/accounts','/admin/jobs','/admin/resumes','/admin/events','/admin/governance']:
   visit(page,'admin',path)
   if path in ['/admin/enterprise-reviews','/admin/governance']:page.screenshot(path=str(OUT/('admin-'+path.split('/')[-1]+'.jpg')),full_page=True)
   visit(page,'admin',path,390)
  ctx.close();browser.close()
 report={'route_viewport_checks':len(checks),'checks':checks,'enabled_action':state_styles,'disabled_action':disabled_style,'page_errors':errors,'overflows':overflows}
 (OUT/'qa.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False))
 assert not errors,errors
 assert not overflows,overflows

if __name__=='__main__': main()
