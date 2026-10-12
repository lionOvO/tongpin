"""Browser acceptance against running local services; outputs screenshots and JSON."""
import json
import os
import httpx
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts';OUT.mkdir(exist_ok=True)
BASE=os.getenv('WEB_URL','http://127.0.0.1:8501')


def main():
    errors=[];checks=[]
    with sync_playwright() as p:
        executable=os.getenv('PLAYWRIGHT_BROWSER',r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
        browser=p.chromium.launch(executable_path=executable,headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1050},device_scale_factor=1)
        page.on('pageerror',lambda e:errors.append(str(e)))
        def loaded():
            page.wait_for_selector('.page-heading h1',timeout=60000)
            page.wait_for_timeout(1200)
            page.wait_for_selector('[data-testid="stApp"][data-test-script-state="notRunning"]',timeout=60000)
            page.wait_for_function("!document.querySelector('[data-testid=stException]')",timeout=10000)
        page.goto(BASE);loaded()
        page.get_by_text('好的相遇，始于彼此理解。',exact=True).wait_for()
        page.screenshot(path=str(OUT/'desktop-matches.png'),full_page=True)
        for path in ['preferences','jobs','profile','requirements','resumes','reports','ranking','audit','config','selfcheck']:
            page.goto(BASE+'/'+path);loaded()
            assert page.locator('[data-testid=stException]').count()==0,path
            heading=page.locator('.page-heading h1').inner_text()
            checks.append({'side':'enterprise','page':path,'heading':heading,'status':'passed'})
            print('enterprise: '+path+' passed',flush=True)
        page.goto(BASE+'/reports');loaded()
        assert '可能存在偏差' in page.locator('[data-testid=stMain]').inner_text()
        page.screenshot(path=str(OUT/'desktop-report.png'),full_page=True)
        api=os.getenv('API_BASE_URL','http://127.0.0.1:8000')
        old=httpx.get(api+'/assessments').json()[0]
        response=httpx.post(api+'/assessments',json={'job_id':old['job_id'],'resume_ids':[old['resume_id']]},timeout=180)
        assert response.status_code==200 and response.json()['reports']
        page.goto(BASE+'/reports');loaded()
        page.get_by_role('textbox',name='审阅理由（必填）',exact=True).fill('自动化验收：核对合成样本原文后确认，供演示使用。')
        page.get_by_role('textbox',name='审阅理由（必填）',exact=True).press('Tab')
        loaded()
        page.get_by_role('button',name='保存审阅结果',exact=True).click()
        try:
            page.locator('.badge').filter(has_text='已确认').wait_for(timeout=30000)
        except Exception:
            (OUT/'review-failure.txt').write_text(page.locator('[data-testid=stMain]').inner_text(),encoding='utf-8')
            page.screenshot(path=str(OUT/'review-failure.png'))
            raise
        page.goto(BASE+'/ranking');loaded()
        page.get_by_role('button',name='导出候选人名单',exact=True).wait_for(timeout=15000)
        checks.append({'flow':'human-confirmation-to-ranking','status':'passed'})
        print('enterprise: review and ranking passed',flush=True)
        page.goto(BASE+'/preferences');loaded()
        page.get_by_role('button',name='保存偏好',exact=True).click()
        page.get_by_text('偏好已保存。历史结果仍使用原填报，重新对照后可查看最新结果。',exact=True).wait_for(timeout=15000)
        checks.append({'flow':'save-enterprise-preference','status':'passed'})
        pairs=httpx.get(api+'/matches').json()
        for pair in {(m['job_id'],m['resume_id']) for m in pairs}:
            response=httpx.post(api+'/matches/run',json={'job_id':pair[0],'resume_id':pair[1]})
            assert response.status_code==200
        page.goto(BASE);loaded()
        page.screenshot(path=str(OUT/'desktop-matches.png'),full_page=True)
        cfg=json.loads((ROOT/'config'/'presentation.json').read_text(encoding='utf-8'))
        text=page.locator('[data-testid=stMain]').inner_text().replace('系统不设合格线','')
        assert not any(term in text for term in cfg['banned_terms']+cfg['enterprise_banned_terms']),text
        page.get_by_role('combobox',name='当前视角',exact=True).click()
        page.get_by_role('option',name='求职者视角',exact=True).click()
        page.get_by_role('combobox',name='演示身份',exact=True).wait_for(timeout=15000)
        page.get_by_text('我的岗位对照',exact=True).wait_for(timeout=15000)
        loaded()
        print('candidate: switched role',flush=True)
        (OUT/'candidate-navigation.txt').write_text(page.locator('[data-testid=stSidebar]').aria_snapshot(),encoding='utf-8')
        page.screenshot(path=str(OUT/'candidate-matches.png'),full_page=True)
        for label in ['我的偏好','我的简历','岗位对照分析','岗位对照排序','岗位参考基准']:
            page.locator('[data-testid=stSidebar]').get_by_text(label,exact=True).click();loaded()
            assert page.locator('[data-testid=stException]').count()==0,label
            checks.append({'side':'candidate','page':label,'status':'passed'})
            print('candidate: '+label+' passed',flush=True)
        page.locator('[data-testid=stSidebar]').get_by_text('岗位对照分析',exact=True).click();loaded()
        page.get_by_role('button',name='开始岗位对照',exact=True).click()
        page.get_by_text('逐项查看依据',exact=True).wait_for(timeout=30000)
        assert page.get_by_text('面试准备',exact=False).count()==0
        checks.append({'flow':'candidate-fit-analysis','status':'passed'})
        page.screenshot(path=str(OUT/'candidate-fit.png'),full_page=True)
        page.locator('[data-testid=stSidebar]').get_by_text('匹配建议',exact=True).click();loaded()
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_timeout(800)
        overflow=page.evaluate('document.documentElement.scrollWidth > window.innerWidth + 2')
        assert not overflow,'mobile horizontal overflow'
        page.screenshot(path=str(OUT/'mobile-matches.png'),full_page=True)
        checks.append({'flow':'mobile-390px','status':'passed'})
        browser.close()
    result={'checks':checks,'page_errors':errors}
    (OUT/'browser-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    assert not errors,errors


if __name__=='__main__':main()
