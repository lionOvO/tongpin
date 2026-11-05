"""Synthetic job-fit journey; intercept every API call and never write live business data."""
import copy
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

URL = os.getenv('JOB_FIT_URL', 'http://127.0.0.1:8502')
OUT = Path(os.getenv('JOB_FIT_OUT', 'artifacts/job-fit-browser')); OUT.mkdir(parents=True, exist_ok=True)


def run():
    errors, writes, records = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        context = browser.new_context(viewport={'width':1440,'height':1000})
        page = context.new_page(); page.on('pageerror', lambda e: errors.append(str(e)))
        jobs = [dict(id=f'job-{i}', title=title, company_name=f'合成公司 {i+1}', status='已确认', version=2,
                     profile={'direction':'软件开发','education':'本科','requirements':[{'skill':'Python','required_level':2,'quote':'使用 Python 开发接口','hard':True}]})
                for i,title in enumerate(['Python 后端工程师','数据开发工程师','平台运维工程师','Agent 应用工程师','前端开发工程师','产品经理'])]
        resumes = [dict(id=f'resume-{i}',display_name=f'合成简历 {i+1}',text='使用 Python 开发业务接口，与团队协作完成数据系统项目。',data_origin='synthetic') for i in range(2)]
        dims = [{'dimension_id':'D3','name':'项目经验','tier':'B4','rationale':'有相关项目职责描述。','evidence':['使用 Python 开发业务接口，与团队协作完成数据系统项目。']}]
        results = []
        for i,(band,label) in enumerate([('very_high','很高契合'),('high','较高契合'),('medium','一般契合'),('low','较低契合'),('very_low','很低契合'),('unassessed','暂无判断依据')]):
            results.append({'job_ref':i+1,'job_id':jobs[i]['id'],'company_name':jobs[i]['company_name'],'job_title':jobs[i]['title'],'rank':None if i==5 else i+1,'dimensions':dims,'skill_levels':[{'skill':'Python','hard':True,'tier':'B4','requirement_quote':'使用 Python 开发接口','evidence':['使用 Python 开发业务接口，与团队协作完成数据系统项目。']}],
                            'fit_summary':{'band':band,'label':label,'reason':'现有项目与技术描述支持逐项对照。','strengths':['接口开发'],'gaps':['部署经验'] if i in [1,2] else [],'missing':['项目职责'] if i in [1,5] else [],'additional_missing':['学业表现'],'coverage':{'known':0 if i==5 else 1,'total':3}}})
        tasks = []; polls = 0
        def api(route):
            nonlocal tasks, polls
            req=route.request; path=urlparse(req.url).path.removeprefix('/api')
            if req.method != 'GET': writes.append({'path':path,'intercepted':True,'method':req.method})
            if path=='/auth/me': data={'user':{'id':'synthetic','actor':'candidate:synthetic','role':'candidate','workspace_role':'candidate','name':'演示用户','has_password':True},'csrf_token':'mock-csrf'}
            elif path=='/jobs': data=jobs
            elif path=='/jobs/references':
                body=req.post_data_json
                data=dict(id='private-reference',title=body['title'],source_jd=body['jd'],personal_reference=True,published=False,status='已确认',version=1,data_origin='real',profile={'direction':'数据开发','education':None,'requirements':[]})
                jobs.insert(0,data)
            elif path=='/resumes': data=resumes
            elif path=='/config/rubric': data={'skill_names':{'2':'熟悉'}}
            elif path=='/health': data={'status':'ok','llm_mode':'demo'}
            elif path=='/config/presentation': data={'tier_labels':{'B4':'相符','insufficient':'证据不足'},'banned_terms':[],'enterprise_banned_terms':[],'bias_notice':'基于授权材料，仅供参考。','footer':'由双方决定下一步。'}
            elif path.startswith('/messages/conversations/page'): data={'items':[],'total':0,'unread_total':0}
            elif path=='/compare/tasks':
                body=req.post_data_json
                assert req.headers.get('x-csrf-token')=='mock-csrf'
                assert body['resume_id'] in [r['id'] for r in resumes]
                task={'id':'task-'+str(len(tasks)),'status':'running','resume_id':body['resume_id'],'resume_name':'合成简历 1','created_at':'2026-10-17T08:00:00Z','total':len(body.get('job_ids') or body['job_texts']),'processed':0,'errors':[],'ranked_results':[],'model':{'id':'deepseek'},'data_origin':'synthetic'}
                tasks.insert(0,task); data=task; polls=0
            elif path=='/compare/runs':
                polls+=1
                if tasks and polls>=2: tasks[0].update(status='completed',processed=tasks[0]['total'],ranked_results=copy.deepcopy(results))
                data=tasks
            elif path.startswith('/fit/benchmark'):
                route.fulfill(status=400,json={'detail':{'code':'INSUFFICIENT_SAMPLES','message':'合成样本不足'}}); return
            else: data=[]
            route.fulfill(status=200,json=data)
        page.route('**/api/**',api)
        page.goto(URL+'/compare?job=job-0',wait_until='networkidle')
        page.get_by_role('heading',name='岗位契合度',exact=True).wait_for()
        expect(page.get_by_label('选择岗位：Python 后端工程师',exact=True)).to_be_checked()
        page.get_by_role('button',name='全选岗位',exact=True).click()
        expect(page.get_by_role('checkbox',checked=True)).to_have_count(6)
        expect(page.get_by_role('button',name='全选岗位',exact=True)).to_be_disabled()
        page.get_by_role('button',name='清空选择',exact=True).click()
        page.get_by_label('搜索目标岗位',exact=True).fill('Agent')
        page.get_by_role('button',name='全选搜索结果',exact=True).click()
        page.get_by_label('搜索目标岗位',exact=True).clear()
        expect(page.get_by_role('checkbox',checked=True)).to_have_count(1)
        expect(page.get_by_label('选择岗位：Agent 应用工程师',exact=True)).to_be_checked()
        page.get_by_role('button',name='全选岗位',exact=True).click()
        page.get_by_role('button',name='分析岗位契合度',exact=True).click()
        expect(page.get_by_role('button',name='该简历正在分析',exact=True)).to_be_disabled()
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        expect(page.locator('.fit-result-card')).to_have_count(6)
        assert '暂不排位' in page.locator('.fit-result-card.unassessed').inner_text()
        assert page.locator('.fit-result-card.very_high').get_by_text('很高契合',exact=True).count()==1
        page.locator('.fit-result-card').first.locator('summary').click()
        assert '使用 Python 开发业务接口' in page.locator('.fit-result-card').first.inner_text()
        for width,height in [(1920,1080),(1440,1000),(1024,768),(768,1024),(390,844),(360,740)]:
            page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(150)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            for selector in ['.fit-builder','.fit-band-counts','.fit-result-card']:
                box=page.locator(selector).first.bounding_box()
                assert box['x']>=0 and box['x']+box['width']<=width+1,(selector,width,box)
            if width in [1440,390]: page.screenshot(path=str(OUT/f'job-fit-{width}.png'),full_page=True)
            records.append({'viewport':width,'overflow':False})
        page.set_viewport_size({'width':1440,'height':1000})
        page.get_by_role('button',name='添加岗位',exact=True).click()
        expect(page.get_by_role('button',name='添加并选中',exact=True)).to_be_disabled()
        page.locator('#reference-job-name').fill('合成数据开发岗位')
        page.locator('#reference-job-description').fill('合成数据开发岗位，要求 SQL 与 Python，参与业务报表和数据处理项目。')
        page.get_by_role('button',name='取消',exact=True).click()
        assert page.get_by_role('checkbox',checked=True).count()==6
        page.get_by_label('搜索目标岗位',exact=True).fill('Agent');expect(page.locator('.fit-job-option')).to_have_count(1)
        page.get_by_role('button',name='添加岗位',exact=True).click()
        page.locator('#reference-job-name').fill('合成数据开发岗位')
        page.locator('#reference-job-description').fill('合成数据开发岗位，要求 SQL 与 Python，参与业务报表和数据处理项目。')
        page.get_by_role('button',name='添加并选中',exact=True).click()
        expect(page.get_by_role('dialog')).not_to_be_visible()
        expect(page.get_by_label('搜索目标岗位',exact=True)).to_have_value('')
        expect(page.get_by_role('checkbox',checked=True)).to_have_count(7)
        expect(page.get_by_text('个人参照 · 仅自己可见',exact=True)).to_be_visible()
        page.get_by_role('button',name='分析岗位契合度',exact=True).click()
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        expect(page.locator('.fit-result-card')).to_have_count(6)
        page.reload(wait_until='networkidle');expect(page.locator('.fit-result-card')).to_have_count(6)
        page.locator('.fit-resume select').select_option('resume-1');expect(page.locator('.fit-result-card')).to_have_count(0)
        page.locator('.fit-resume select').select_option('resume-0');expect(page.locator('.fit-result-card')).to_have_count(6)
        page.emulate_media(reduced_motion='reduce')
        assert page.locator('.fit-job-option').first.evaluate('e=>getComputedStyle(e).transitionDuration')=='0s'
        page.get_by_role('button',name='岗位参考基准',exact=True).click()
        expect(page.get_by_role('heading',name='岗位要求参照',exact=True)).to_be_visible()
        page.locator('#reference-target-job').select_option('job-0')
        expect(page.get_by_text('暂未提供可用的同类岗位统计。可先按上方岗位原文了解要求，不影响契合度分析。',exact=True)).to_be_visible()
        expect(page.get_by_text('使用 Python 开发接口',exact=True)).to_be_visible()
        expect(page.get_by_text('熟悉 · 2 级',exact=True)).to_be_visible()
        for width in [1440,1024,768,390,360]:
            page.set_viewport_size({'width':width,'height':960})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'reference overflow {width}'
            page.screenshot(path=str(OUT/f'job-reference-{width}.png'),full_page=True)
        page.route('**/api/fit/benchmark?**',lambda r:r.fulfill(status=200,json=[{'id':'stat-one','skill':'Python','lower_level':1,'upper_level':3,'sample_size':20,'source_type':'B_synthetic'}]))
        page.get_by_role('button',name='刷新统计',exact=True).click()
        expect(page.get_by_text('20 个不同岗位 · 合成样例统计，非真实招聘数据',exact=True)).to_be_visible()
        page.screenshot(path=str(OUT/'job-reference-statistics-mobile.png'),full_page=True)
        assert len(writes)==3 and len([r for r in writes if r['path']=='/compare/tasks'])==2 and len([r for r in writes if r['path']=='/jobs/references'])==1
        browser.close()
    assert not errors,errors
    record={'cases':records,'checks':['existing jobs preselected and multi-select','DeepSeek background progress','five bands, known-evidence coverage and unassessed notice','expandable exact evidence','private reference modal, auto-selection and mixed submission','search','history and resume isolation','reload recovery','benchmark preserved','reduced motion'], 'page_errors':errors,'mocked_writes':writes,'real_business_writes':0}
    (OUT/'verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(record,ensure_ascii=False))


if __name__=='__main__': run()
