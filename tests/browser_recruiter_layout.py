"""Recruiter desk layout QA against synthetic preview services only."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts'/'recruiter-layout'
BASE='http://127.0.0.1:8519'

def main():
 OUT.mkdir(parents=True,exist_ok=True); errors=[];results=[]
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
  page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(BASE+'/login?role=enterprise');page.locator('#auth-phone').fill('13800000991');page.locator('#auth-password').fill('Scenario-password-2026');page.locator('form button.primary').click();page.wait_for_url('**/workspace')
  page.goto(BASE+'/recruiter-ai');page.locator('.recruiter-ai-candidate-list button').filter(has_text='陈予安').click();page.wait_for_function("document.querySelector('.recruiter-shortcuts button')?.disabled===false")
  page.get_by_role('button',name='已有对话',exact=False).click();assert page.locator('.recruiter-ai-candidate-list button').count()==1
  page.get_by_role('button',name='全部投递',exact=True).click();assert page.locator('.recruiter-ai-candidate-list button').count()==3
  page.locator('#recruiter-ai-search').fill('林知夏');assert page.locator('.recruiter-ai-candidate-list button').count()==1
  page.locator('#recruiter-ai-search').clear()
  page.get_by_role('button',name='补充业务背景',exact=True).click();page.locator('#recruiter-business-input').fill('维护订单查询接口，与运营同事核对查询条件。')
  page.get_by_role('button',name='收起业务背景',exact=True).click();assert page.locator('#recruiter-business-input').count()==0
  page.get_by_role('button',name='业务背景已补充',exact=True).click();assert '订单查询' in page.locator('#recruiter-business-input').input_value()
  page.get_by_role('button',name='收起业务背景',exact=True).click()
  for width,height in [(1440,1000),(1366,768),(1024,768),(390,844),(360,740)]:
   page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(150)
   geom=page.evaluate('''()=>{let log=document.querySelector('.recruiter-chat-log'), composer=document.querySelector('.recruiter-composer'),r=composer.getBoundingClientRect();return {width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,chatHeight:log.clientHeight,composerBottom:r.bottom,composerWidth:r.width,listOverflow:getComputedStyle(document.querySelector('.recruiter-ai-candidate-list')).overflowY}}''')
   assert geom['scrollWidth']<=width,(width,geom)
   assert geom['scrollHeight']<=height,(height,geom)
   assert geom['composerBottom']<=height and geom['chatHeight']>=140,geom
   assert geom['listOverflow']=='auto',geom
   results.append(geom)
   if width in [1440,390,360]:page.screenshot(path=str(OUT/f'desk-{width}.jpg'),full_page=True)
   page.get_by_role('button',name='补充业务背景',exact=True).click() if page.get_by_role('button',name='补充业务背景',exact=True).count() else page.get_by_role('button',name='业务背景已补充',exact=True).click()
   assert page.locator('.recruiter-composer').bounding_box()['y']+page.locator('.recruiter-composer').bounding_box()['height']<=height
   page.get_by_role('button',name='收起业务背景',exact=True).click()
   if width<981:
    page.get_by_role('button',name='切换候选人',exact=False).click();assert page.locator('.recruiter-ai-candidates').is_visible();assert not page.locator('.recruiter-ai-content').is_visible()
    if width==390:page.screenshot(path=str(OUT/'candidate-picker-mobile.jpg'),full_page=True)
    page.locator('.recruiter-ai-candidate-list button').filter(has_text='林知夏').click();page.get_by_text('从具体经历开始了解。',exact=True).wait_for();assert not page.locator('.recruiter-ai-candidates').is_visible()
    assert page.locator('.recruiter-ai-subject').inner_text().startswith('林')
    page.get_by_role('button',name='切换候选人',exact=False).click();page.locator('.recruiter-ai-candidate-list button').filter(has_text='陈予安').click();page.wait_for_function("document.querySelector('.recruiter-shortcuts button')?.disabled===false")
   page.get_by_role('button',name='资料卡与技术图谱',exact=True).click();page.get_by_text('核心技术经历',exact=True).wait_for()
   assert page.locator('.recruiter-ai-profile').evaluate('(e)=>getComputedStyle(e).overflowY')=='auto'
   assert page.evaluate('document.documentElement.scrollWidth')<=width
   if width==1440:page.screenshot(path=str(OUT/'technical-profile.jpg'),full_page=True)
   page.get_by_role('button',name='授权材料',exact=True).click();assert 'FastAPI' in page.locator('.recruiter-ai-materials').inner_text()
   page.get_by_role('button',name='AI 对话',exact=True).click()
  page.set_viewport_size({'width':1440,'height':1000});page.get_by_role('button',name='专注对话',exact=True).click();assert not page.locator('.recruiter-ai-candidates').is_visible();assert page.locator('.recruiter-composer').bounding_box()['width']>1000
  page.screenshot(path=str(OUT/'focused.jpg'),full_page=True);page.get_by_role('button',name='返回工作台',exact=True).click()
  # A short landscape window can scroll to the composer instead of clipping it.
  page.set_viewport_size({'width':844,'height':390});page.wait_for_timeout(150);page.locator('.recruiter-composer').scroll_into_view_if_needed();box=page.locator('.recruiter-composer').bounding_box();assert box['y']+box['height']<=390
  assert page.evaluate('document.documentElement.scrollWidth')<=844
  browser.close()
 report={'viewports':results,'page_errors':errors,'checks':['history filter','search','business context disclosure preserves draft','composer visible without page scrolling','independent list and reading scroll','mobile candidate selection','profile and materials tabs','focus mode','short landscape input reachable']}
 (OUT/'qa.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False));assert not errors,errors

if __name__=='__main__':main()
