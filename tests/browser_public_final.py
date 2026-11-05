"""Closing-screen handoff: real wheel frames, reverse, alignment and accessible fallback."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

URL=os.environ.get('PUBLIC_HOME_URL','http://127.0.0.1:5188')
OUT=Path(os.environ.get('PUBLIC_HOME_FINAL_OUT','artifacts/public-home/final'));OUT.mkdir(parents=True,exist_ok=True)

def run():
 errors=[];writes=[];results=[]
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
  page=browser.new_page(viewport={'width':1920,'height':920})
  def api(route):
   if route.request.method!='GET':writes.append(route.request.url)
   route.fulfill(status=401,json={'detail':'Login required'})
  page.route('**/api/**',api);page.on('pageerror',lambda e:errors.append(str(e)))
  for w,h in [(1920,920),(1440,1000),(1366,768),(1024,740),(1920,1080)]:
   page.set_viewport_size({'width':w,'height':h});page.goto(URL,wait_until='networkidle')
   page.locator('.tp-sections button').nth(4).click();page.wait_for_timeout(1500)
   assert page.locator('.tp-story-stage').evaluate('e=>!e.inert')
   if w==1920 and h==920:
    unit=max(800,min(1000,h*.95));start=unit*(4.75+1.2*.66);span=unit*1.2*.34
    def pose():return page.evaluate('''()=>{const final=document.querySelector('.tp-final'),bg=getComputedStyle(final,'::before'),journey=document.querySelector('#tp-journey');return{
     top:final.getBoundingClientRect().top,bg:bg.transform,bgOpacity:+bg.opacity,
     title:+getComputedStyle(final.querySelector('h2')).opacity,actions:+getComputedStyle(final.querySelector('.tp-entry-actions')).opacity,
     journey:+getComputedStyle(journey).opacity,card:getComputedStyle(journey.querySelector('.tp-journey-demo')).transform,
     inert:final.inert,stageInert:document.querySelector('.tp-story-stage').inert}}''')
    frames=[]
    for t in [.08,.24,.45,.65,.85,1]:
     page.evaluate('y=>scrollTo(0,y)',start+span*t);page.wait_for_timeout(950)
     sample=pose();frames.append(sample)
     assert abs(sample['top']-88)<1,sample
     assert not(sample['journey']>.001 and sample['title']>.001),sample
     if t in [.24,.65,1]:page.screenshot(path=str(OUT/f'closing-{t}.png'))
    assert len(set(f['bg'] for f in frames))>=5
    assert frames[0]['journey']>0 and frames[0]['title']==0 and frames[0]['inert']
    assert frames[-1]['actions']==1 and not frames[-1]['inert'] and frames[-1]['stageInert']
    page.evaluate('y=>scrollTo(0,y)',start+span*.24);page.wait_for_timeout(950)
    reverse=pose();assert abs(reverse['bgOpacity']-frames[1]['bgOpacity'])<.005
    assert abs(reverse['journey']-frames[1]['journey'])<.005
    # A real wheel gesture must produce multiple in-between shapes, not a swap.
    page.evaluate('y=>scrollTo(0,y)',start);page.wait_for_timeout(950)
    page.mouse.wheel(0,span)
    wheel=page.evaluate('''async()=>{const frames=[];await new Promise(resolve=>{function sample(){
      frames.push(getComputedStyle(document.querySelector('.tp-final'),'::before').transform);
      if(frames.length<40)requestAnimationFrame(sample);else resolve()};requestAnimationFrame(sample)});return frames}''')
    assert len(set(wheel))>=8,len(set(wheel))
    results.append({'closing_transition':frames,'reverse':'passed','distinct_wheel_frames':len(set(wheel))})
    page.locator('.tp-sections button').nth(4).click();page.wait_for_timeout(1500)
   # The bottom interaction toolbar was removed; reach the closing scene by
   # natural scrolling, which remains the primary way through the narrative.
   page.evaluate("scrollTo(0,document.querySelector('.tp-story-track').getBoundingClientRect().bottom+scrollY-88)");page.wait_for_timeout(1400)
   state=page.evaluate('''()=>{const final=document.querySelector('.tp-final'),stage=document.querySelector('.tp-story-stage'),content=final.firstElementChild;
    const f=final.getBoundingClientRect(),c=content.getBoundingClientRect();return{top:f.top,height:f.height,center:c.top+c.height/2,
     stageBottom:stage.getBoundingClientRect().bottom,inert:stage.inert,hidden:stage.getAttribute('aria-hidden'),visibility:getComputedStyle(stage).visibility,
     overflow:document.documentElement.scrollWidth>innerWidth}}''')
   page.screenshot(path=str(OUT/f'{w}x{h}-aligned.png'))
   assert abs(state['top']-88)<2,(w,h,state)
   assert abs(state['center']-(88+(h-88)/2))<2,(w,h,state)
   assert state['inert'] and state['hidden']=='true' and state['visibility']=='hidden',(w,h,state)
   assert not state['overflow']
   # Natural scrolling to the absolute bottom cannot leave the old progress bar.
   page.evaluate('scrollTo(0,document.documentElement.scrollHeight)');page.wait_for_timeout(700)
   assert page.locator('.tp-story-stage').evaluate('e=>e.inert && getComputedStyle(e).visibility==="hidden"')
   # Closing-screen entries still lead to the original login flow.
   if w==1920 and h==920:
    page.get_by_role('button',name='准备我的经历',exact=True).click();page.wait_for_url('**/login?role=candidate')
    page.go_back(wait_until='networkidle');page.wait_for_timeout(500)
   page.locator('.tp-sections button').nth(4).click();page.wait_for_timeout(1500)
   assert page.locator('.tp-story-stage').evaluate('e=>!e.inert && !e.hasAttribute("aria-hidden") && getComputedStyle(e).visibility==="visible"')
   page.locator('.tp-journey-track button').nth(3).click()
   page.locator('.tp-chat-demo').wait_for(state='visible')
   assert page.get_by_label('试写一条演示消息').is_visible()
   results.append({'viewport':f'{w}x{h}','closing_screen':state,'return_to_story':'passed'})
  for w,h,reduce in [(390,844,False),(844,390,False),(1440,1000,True)]:
   page.set_viewport_size({'width':w,'height':h});page.emulate_media(reduced_motion='reduce' if reduce else 'no-preference')
   page.goto(URL,wait_until='networkidle');page.locator('.tp-final').scroll_into_view_if_needed();page.wait_for_timeout(200)
   assert not page.locator('.tp-fixed').count()
   assert page.locator('.tp-story-stage').evaluate('e=>!e.inert && !e.hasAttribute("aria-hidden")')
   assert page.get_by_role('button',name='准备我的经历',exact=True).is_visible()
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   results.append({'viewport':f'{w}x{h}','reduced_motion':reduce,'flow':'passed'})
  assert not errors and not writes,(errors,writes)
  browser.close()
 record={'cases':results,'page_errors':errors,'business_writes':writes}
 (OUT/'verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps(record,ensure_ascii=False))
if __name__=='__main__':run()
