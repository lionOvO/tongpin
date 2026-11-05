"""Fixed-canvas acceptance: actual wheel scrubbing, replay, inactive focus and fallback."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright
OUT=Path('artifacts/public-home/fixed');OUT.mkdir(parents=True,exist_ok=True)
URL=os.environ.get('PUBLIC_HOME_URL','http://127.0.0.1:5188')
def run():
 errors=[];writes=[];result={}
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
  page=browser.new_page(viewport={'width':1440,'height':1000})
  def api(r):
   if r.request.method!='GET':writes.append(r.request.url)
   r.fulfill(status=401,json={'detail':'Login required'})
  page.route('**/api/**',api);page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(URL,wait_until='networkidle')
  page.get_by_role('button',name='个人资料演示',exact=True).click();page.wait_for_timeout(2300)
  def scroll(y):
   # Geometry seeks are instant: otherwise the browser's CSS smooth scroll and
   # the scene's own easing both need to settle. Real wheel/nav motion is tested below.
   page.evaluate('y=>scrollTo({top:y,behavior:"instant"})',y);page.wait_for_timeout(850)
  def gather():return page.locator('.tp-hero-track').evaluate('e=>+e.style.getPropertyValue("--gather")')
  def nav(i):
   page.locator('.tp-sections button').nth(i).click();page.wait_for_timeout(1400)
  def unit():return page.evaluate('Math.max(800,Math.min(1000,innerHeight*.95))')
  def state():return page.locator('.tp-story-stage>section').evaluate_all('es=>es.map(e=>({opacity:+getComputedStyle(e).opacity,inert:e.inert,hidden:e.getAttribute("aria-hidden"),top:e.getBoundingClientRect().top}))')
  assert gather()==1
  # Replay has real intermediate frames even without any scrolling, and is repeatable.
  replays=[]
  for _ in range(3):
   page.get_by_role('button',name='重新整理',exact=True).click();page.wait_for_timeout(90);early=gather()
   page.wait_for_timeout(800);middle=gather();page.wait_for_timeout(1400);end=gather()
   assert early<.1 and .1<middle<.95 and end==1,(early,middle,end)
   replays.append([early,middle,end])
  for i in [1,2,0]:
   page.locator('.tp-person-picker button').nth(i).click();page.wait_for_timeout(100);assert gather()<.1
   page.wait_for_timeout(2200);assert gather()==1
  nav(3);nav(0);page.wait_for_timeout(2300);assert gather()==1
  page.get_by_role('link',name='同频首页',exact=True).click();page.wait_for_timeout(100);assert gather()<.1
  page.wait_for_timeout(2200);assert gather()==1
  # Real scroll changes only the scene state. The canvas stays at top 88 throughout.
  u=unit();samples=[]
  for y in [0,.35*u,.66*u,.7*u,.74*u,.8*u,.83*u,.88*u,.92*u,.96*u,u,1.35*u]:
   scroll(y);s=state();top=page.locator('.tp-story-stage').evaluate('e=>e.getBoundingClientRect().top')
   assert abs(top-88)<.1,(y,top)
   assert sum(e['opacity'] for e in s)<=1.001,(y,s)
   assert len([e for e in s if e['opacity']>.001])<=1,(y,s)
   bridge=page.locator('.tp-story-track').evaluate('e=>+e.style.getPropertyValue("--bridge-opacity")')
   assert abs(sum(e['opacity'] for e in s)+bridge-1)<.001
   assert len([e for e in s if not e['inert']])==1
   assert all(e['hidden']==str(e['inert']).lower() for e in s)
   samples.append({'y':y,'opacity':[e['opacity'] for e in s],'stage_top':top})
  assert len(set(round(s['opacity'][0],3) for s in samples))>=4
  for y in [.88*u,.8*u,.35*u]:
   scroll(y);expected=min(samples,key=lambda s:abs(s['y']-y))
   assert all(abs(a['opacity']-b)<.001 for a,b in zip(state(),expected['opacity'])),(y,state(),expected)
  # Each handoff folds the actual panel, carries one identity, then unfolds it.
  # These checks would fail for a stationary card plus section opacity fades.
  transfers=[]
  starts=[0,1,2.1,3.6];spans=[1,1.1,1.5,1.15]
  for i in range(4):
   poses=[]
   for t in [.02,.2,.5,.8,.98]:
    scroll(u*(starts[i]+spans[i]*(.66+.34*t)))
    paper=page.locator('.tp-transition-paper').evaluate('e=>({matrix:getComputedStyle(e).transform,rect:e.getBoundingClientRect().toJSON()})')
    identity=page.locator('.tp-transition-identity').evaluate('e=>+getComputedStyle(e).opacity')
    assert not (identity>.001 and max(e['opacity'] for e in state())>.001),(i,t,identity,state())
    poses.append(paper)
    if t==.5:page.screenshot(path=str(OUT/f'transfer-{i}-midpoint.png'))
   assert poses[2]['rect']['width']<min(poses[0]['rect']['width'],poses[-1]['rect']['width'])*.85
   assert len(set(x['matrix'] for x in poses))==5
   scroll(u*(starts[i]+spans[i]*(.66+.34*.2)))
   reverse=page.locator('.tp-transition-paper').evaluate('e=>e.getBoundingClientRect().toJSON()')
   assert abs(reverse['x']-poses[1]['rect']['x'])<1.5
   transfers.append({'handoff':i,'rectangles':[x['rect'] for x in poses],'reverse':'passed'})
  scroll(.83*u);page.screenshot(path=str(OUT/'transition-midpoint.png'))
  scroll(u*.66);page.mouse.wheel(0,u*.32)
  wheel=page.evaluate('''async()=>{const frames=[];await new Promise(resolve=>{
    function sample(){frames.push(getComputedStyle(document.querySelector('.tp-transition-paper')).transform);
      if(frames.length<36)requestAnimationFrame(sample);else resolve()};requestAnimationFrame(sample)});return frames}''')
  assert abs(page.evaluate('scrollY')-u*.98)<2
  assert len(set(wheel))>=5
  page.wait_for_timeout(700);settled=state();page.wait_for_timeout(350);assert state()==settled
  # Continuous drawing, reverse progress and manual override within the same canvas.
  scroll(u+u*1.1*.66*.4)
  offsets=page.locator('.tp-connection-lines path').evaluate_all('es=>es.map(e=>parseFloat(getComputedStyle(e).strokeDashoffset.replace("calc(","")))')
  assert offsets[0]==0 and 0<offsets[1]<100 and offsets[2]==100,offsets
  page.locator('.tp-relation-list button').nth(2).click();scroll(u+10)
  assert page.locator('.tp-relation-list button').nth(2).get_attribute('aria-pressed')=='true'
  start=u*(1+1.1+1.5+1.15);span=u*1.2
  for progress,step in [(.01,0),(.3,1),(.6,2),(.9,3),(.02,0)]:
   scroll(start+span*.66*progress)
   assert page.locator('.tp-journey-stage').get_attribute('data-step')==str(step)
  # All five scenes and every displayed card fit within the fixed viewport.
  layouts=[]
  for w,h in [(1440,1000),(1366,768),(1024,740),(1920,1080),(1536,730),(1366,700)]:
   page.set_viewport_size({'width':w,'height':h});page.wait_for_timeout(200)
   for i in range(5):
    nav(i)
    if i==0:page.wait_for_timeout(2200)
    bounds=page.locator('.tp-story-stage>section:not([inert])').evaluate('''e=>[...e.querySelectorAll('.tp-person-card,.tp-scene-figure,.tp-edit-demo,.tp-employer-card,.tp-journey-demo')].map(n=>({name:n.className,top:n.getBoundingClientRect().top,bottom:n.getBoundingClientRect().bottom}))''')
    # No bottom interaction toolbar remains; keep a 16px viewport safety margin.
    assert all(x['top']>=88 and x['bottom']<=h-16 for x in bounds),(w,h,i,bounds)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   layouts.append(f'{w}x{h}: pinned, 5 scenes fit')
  for w,h in [(768,1024),(390,844),(360,740),(844,390),(1366,620)]:
   page.set_viewport_size({'width':w,'height':h});page.wait_for_timeout(250);scroll(0)
   assert not page.locator('.tp-fixed').count()
   assert page.locator('.tp-story-stage>section[inert]').count()==0
   assert page.locator('.tp-story-track').evaluate('e=>e.style.height')==''
   for selector in ['.tp-hero-track','#tp-connect','#tp-edit','#tp-company','#tp-journey']:
    page.locator(selector).scroll_into_view_if_needed();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   layouts.append(f'{w}x{h}: document flow')
  page.set_viewport_size({'width':1440,'height':1000});page.emulate_media(reduced_motion='reduce');scroll(0)
  assert not page.locator('.tp-fixed').count()
  assert page.locator('.tp-person-card').evaluate('e=>getComputedStyle(e).opacity')=='1'
  assert page.locator('.tp-person-card').evaluate('e=>getComputedStyle(e).animationName')=='none'
  page.emulate_media(reduced_motion='no-preference');page.wait_for_timeout(300)
  assert page.locator('.tp-fixed').count()==1
  nav(0);page.wait_for_timeout(2300)
  page.get_by_role('button',name='我要求职',exact=True).click();page.wait_for_url('**/login?role=candidate')
  page.go_back(wait_until='networkidle')
  page.get_by_role('button',name='个人资料演示',exact=True).click();page.wait_for_timeout(2300)
  assert gather()==1
  page.get_by_role('button',name='重新整理',exact=True).click();page.wait_for_timeout(100);assert gather()<.1
  assert not errors and not writes,(errors,writes)
  result={'replays':replays,'scene_crossfade':samples,'moving_paper_transfers':transfers,'wheel_distinct_frames':len(set(wheel)),'reverse_and_idle':'passed','links':offsets,'layouts':layouts,'reentry_and_reduced_motion':'passed','errors':errors,'business_writes':writes}
  browser.close()
 (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':run()
