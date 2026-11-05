"""Resume shelf QA. All API data and writes are synthetic and intercepted locally."""
import json,os,copy
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect
URL=os.environ.get('RESUME_LIBRARY_URL','http://127.0.0.1:8502')
OUT=Path(os.environ.get('RESUME_LIBRARY_OUT','artifacts/resume-library'));OUT.mkdir(parents=True,exist_ok=True)
PEOPLE=[('周雨桐','产品经理助理','需求整理、原型评审、需求文档与项目协作','参与内部协作工具优化，梳理任务流转过程，记录并分类用户反馈。'),('赵启航','测试开发工程师','Python、Pytest、接口测试与持续集成','为订单查询接口编写自动化用例，记录测试数据与复现步骤，协助开发定位问题。'),('吴思琪','数据分析','Python、SQL、数据清洗与可视化','使用 SQL 整理业务数据，以 Python 清洗异常记录，并按周制作运营报表。'),('林若溪','前端开发工程师','Vue、TypeScript、HTML 与 CSS','参与管理端页面开发，实现筛选、分页和表单校验，适配手机屏幕。')]
def fixtures():
 rows=[]
 for i,(name,role,skills,project) in enumerate(PEOPLE*2):
  title='个人简历_'+name+'_'+role+(' · 优化版' if i>3 else '')
  body=f'个人简介\n{name} · 求职方向：{role}\n希望从具体业务中积累项目经验，与团队一起解决实际问题。\n教育经历\n某合成大学 · 计算机相关专业 · 2022—2026\n专业技能\n{skills}\n项目经历\n{project}\n1. 负责整理需求与实施记录，核对过程中的边界情况。\n2. 与团队协作完成验证，保留每次修改的原因和结果。\n3. 将常见问题整理成文档，便于后续维护与交接。\n实习经历\n示例科技有限公司 · 技术实习生\n参与日常任务，整理交付文档，并对待确认信息主动补充说明。\n自我评价\n重视清晰表达与及时反馈，愿意从具体任务中继续学习。'
  if i==0:body+='\n完整正文的末尾保留标记。\n<img src=x onerror=alert(1)>'
  rows.append({'id':f'resume-{i}','display_name':title,'text':body,'data_origin':'synthetic','created_at':f'2026-10-{16-i:02d}T00:00:00Z','supplement_notice':i==4})
 return rows

def run():
 errors=[];records=[];writes=[]
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
  for role in ['candidate','enterprise']:
   context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
   page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
   rows=fixtures();tasks=[];batches=[]
   if role=='enterprise':rows[0].update(source_application_id='application-0',application_job_id='job-one',application_job_title='产品经理助理')
   job={'id':'job-one','title':'产品经理助理','status':'已确认','version':1,'data_origin':'synthetic','source_jd':'整理需求和项目文档。','profile':{'direction':'产品协作','education':'本科','requirements':[]}}
   def api(route):
    nonlocal rows,tasks,batches
    request=route.request;path=urlparse(request.url).path.removeprefix('/api');method=request.method
    if method!='GET':writes.append({'role':role,'method':method,'path':path,'intercepted':True})
    data=None
    if path=='/auth/me':data={'user':{'id':'synthetic-user','actor':'synthetic-'+role,'role':role,'workspace_role':role,'enterprise_status':'approved','name':'演示用户','has_password':True},'csrf_token':'synthetic-csrf'}
    elif path=='/jobs':data=[job]
    elif path=='/config/presentation':data={'version':'test','bias_notice':'分析仅供参考，所有简历均可查看。','footer':'基于授权材料，由双方决定下一步。','tier_labels':{},'preference_labels':{},'banned_terms':[],'enterprise_banned_terms':[]}
    elif path=='/health':data={'status':'ok','llm_mode':'demo','llm_label':'DeepSeek'}
    elif path.startswith('/messages/conversations/page'):data={'items':[],'total':0,'unread_total':0}
    elif path.startswith('/resumes/') and path.endswith('/download'):
     row=next(r for r in rows if r['id']==path.split('/')[2]);route.fulfill(status=200,headers={'Content-Type':'text/plain; charset=utf-8','Content-Disposition':'attachment; filename="resume.txt"'},body=row['text']);return
    elif path.startswith('/resumes/') and method=='DELETE':
     id=path.split('/')[2];rows=[r for r in rows if r['id']!=id];data={'id':id,'deleted':True}
    elif path=='/resumes/batch' and method=='POST':
     row={**fixtures()[0],'id':'file-import','display_name':'上传测试简历'};rows.insert(0,row);data={'resumes':[row],'errors':[]}
    elif path=='/resumes' and method=='POST':
     body=request.post_data_json;row={'id':'text-import','display_name':body['name'],'text':body['text'],'data_origin':body['data_origin'],'created_at':'2026-10-17T01:00:00Z'};rows.insert(0,row);data=row
    elif path=='/resumes':data=rows
    elif path=='/batches/run':
     batches=[{'resume_id':'resume-0','tier':'高匹配','hard_gate_result':'通过','hard_gate_rule_ids':[],'hits':[{'skill':'需求整理','reason':'简历明确写有任务流转与反馈分类经历。','evidence':['参与内部协作工具优化，梳理任务流转过程，记录并分类用户反馈。']}],'misses':[]}];data=batches
    elif path=='/batches':data=batches
    elif path=='/assessment-tasks' and method=='POST':
     body=request.post_data_json;task={'id':'synthetic-task','status':'queued','request_id':body['request_id'],'resume_ids':body['resume_ids'],'model':{'label':'DeepSeek'},'processed':0,'report_ids':[],'errors':[]};tasks=[task];data=task
    elif path=='/assessment-tasks':data=tasks
    else:data=[]
    route.fulfill(status=200,json=data)
   page.route('**/api/**',api)
   page.goto(URL+'/resumes',wait_until='networkidle');page.locator('.resume-library-card').first.wait_for()
   assert page.locator('.resume-collection-grid .resume-library-card').count()==8
   assert page.locator('.resume-library-card .resume-delete-link').count()==8
   assert page.locator('.resume-library-card .resume-download-link').count()==8
   if role=='candidate':assert page.locator('.resume-ai-action').count()==8
   sizes=[]
   for w,h in [(1920,1080),(1440,1000),(1024,768),(768,1024),(390,844),(360,740)]:
    page.set_viewport_size({'width':w,'height':h});page.wait_for_timeout(160)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(role,w)
    geometry=page.locator('.resume-collection').evaluate('(e)=>({columns:getComputedStyle(e).gridTemplateColumns,cardWidth:e.firstElementChild.getBoundingClientRect().width})');sizes.append({'width':w,**geometry})
    if w in [1920,1440,390]:page.screenshot(path=str(OUT/f'{role}-grid-{w}.png'),full_page=True)
    cover=page.locator('.resume-cover-open').first;cover.click()
    dialog=page.get_by_role('dialog');dialog.wait_for();page.wait_for_timeout(350);assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    box=dialog.bounding_box();assert box['x']>=0 and box['x']+box['width']<=w+.5 and box['y']>=0 and box['y']+box['height']<=h+.5,(w,box)
    if w in [1440,390]:page.screenshot(path=str(OUT/f'{role}-reader-{w}.png'))
    page.get_by_role('button',name='分析文本',exact=True).click()
    assert page.locator('.resume-reader-source .source-text').inner_text()==rows[0]['text']
    assert page.locator('.resume-reader img').count()==0
    page.keyboard.press('Escape');assert not page.get_by_role('dialog').count()
    assert cover.evaluate('e=>e===document.activeElement')
   page.set_viewport_size({'width':1440,'height':1000})
   page.get_by_role('button',name='列表视图',exact=True).click();assert page.locator('.resume-collection-list').count()==1
   page.screenshot(path=str(OUT/f'{role}-list.png'),full_page=True)
   page.reload(wait_until='networkidle');assert page.locator('.resume-collection-list').count()==1
   search=page.get_by_role('searchbox',name='搜索简历');search.fill('  SQL  ');assert page.locator('.resume-library-card').count()==0
   page.get_by_role('button',name='清空搜索',exact=True).click();search.fill('赵启航');assert page.locator('.resume-library-card').count()==2
   search.clear();page.get_by_label('简历排序',exact=True).select_option('oldest');assert '林若溪' in page.locator('.resume-card-title').first.inner_text()
   page.get_by_label('简历排序',exact=True).select_option('newest')
   with page.expect_download() as d:page.locator('.resume-download-link').first.click()
   assert Path(d.value.path()).read_text(encoding='utf8')==rows[0]['text']
   page.locator('.resume-delete-link').last.click();assert '已有 AI 对话' in page.get_by_role('dialog').inner_text();page.get_by_role('button',name='取消',exact=True).click();assert len(rows)==8
   page.locator('.resume-delete-link').last.click();page.get_by_role('button',name='确认删除',exact=True).click();expect(page.locator('.resume-library-card')).to_have_count(7)
   page.get_by_role('button',name='导入简历' if role=='candidate' else '本地导入',exact=True).click();page.get_by_role('button',name='粘贴文字',exact=True).click()
   page.get_by_label('展示名称',exact=True).fill('合成测试 · 新导入')
   imported='这是一份合成测试简历，使用 Python 进行数据整理并编写接口测试文档。'
   page.get_by_label('简历原文',exact=True).fill(imported);page.get_by_role('button',name='保存文字简历',exact=True).click();page.get_by_role('dialog').wait_for(state='hidden')
   expect(page.locator('.resume-library-card')).to_have_count(8);assert '合成测试' in page.locator('.resume-card-title').first.inner_text()
   page.get_by_role('button',name='导入简历' if role=='candidate' else '本地导入',exact=True).click();page.get_by_role('button',name='上传文件',exact=True).click()
   page.get_by_label('选择简历文件',exact=True).set_input_files({'name':'synthetic.txt','mimeType':'text/plain','buffer':imported.encode()})
   page.get_by_role('button',name='导入所选文件',exact=True).click();page.get_by_role('dialog').wait_for(state='hidden');expect(page.locator('.resume-library-card')).to_have_count(9)
   if role=='enterprise':
    page.get_by_role('button',name='整理本岗位初筛',exact=True).click();page.wait_for_timeout(100)
    target=page.locator('.resume-library-card').filter(has_text='个人简历_周雨桐_产品经理助理').first
    target.get_by_role('button',name='查看依据',exact=False).click();assert '需求整理' in page.locator('.resume-reader-evidence').inner_text();page.keyboard.press('Escape')
    generate=page.get_by_role('button',name='生成能力报告',exact=True);assert generate.is_disabled()
    target.get_by_role('checkbox').check();page.get_by_role('button',name='卡片视图').click();assert target.get_by_role('checkbox').is_checked();assert generate.is_enabled()
    generate.click();page.get_by_text('报告已排队',exact=True).wait_for();assert tasks[0]['resume_ids']==['resume-0']
    # Revoked source disappears from both the shelf and an open reader on refresh.
    target.get_by_role('button',name='预览简历：个人简历_周雨桐_产品经理助理',exact=True).click()
    rows=[r for r in rows if r['id']!='resume-0'];page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.get_by_role('dialog').wait_for(state='hidden');assert page.locator('.resume-library-card').count()==8
   else:assert '/ai-workspace?resume=' in page.locator('.resume-ai-action').first.get_attribute('href')
   page.emulate_media(reduced_motion='reduce');page.get_by_role('button',name='卡片视图').click();assert page.locator('.resume-cover').first.evaluate('e=>getComputedStyle(e).transitionDuration')=='0s'
   records.append({'role':role,'viewports':sizes,'checks':['grid and list persistence','full source text and escaped markup','reader fits viewport and restores focus','search and sorting','text and file import','download contents','delete confirmation and cancel','original AI route' if role=='candidate' else 'batch evidence, report selection and consent refresh','reduced motion']})
   context.close()
  browser.close()
 assert not errors,errors
 report={'cases':records,'page_errors':errors,'mocked_writes':writes,'real_business_writes':0}
 (OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':run()
