"""Additional PRD presentation assertions; run against an isolated local preview."""
import json
import os
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WEB = os.getenv('WEB_URL', 'http://127.0.0.1:8502')
API = os.getenv('API_BASE_URL', 'http://127.0.0.1:8002')


def main():
    checks, errors = [], []
    config = httpx.get(API + '/config/presentation').json()
    old = next(row for row in httpx.get(API+'/assessments').json() if row['data_origin']=='synthetic')
    fresh = httpx.post(API+'/assessments',json={'job_id':old['job_id'],'resume_ids':[old['resume_id']]},timeout=180).json()
    assert not fresh['errors'] and len(fresh['reports'])==1
    current = fresh['reports'][0]
    assert current['rubric_version']=='rubric-v0.9.6-aligned.1'
    assert current['model_version']=='local-demo-rules-1.1'
    assert current['prompt_version']=='evidence-rubric-v0.9.6-1'
    checks.append({'check':'fresh synthetic report current rubric and prompt versions','status':'passed'})
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_BROWSER', r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'), headless=True)
        page = browser.new_page(viewport={'width':1440, 'height':1050})
        page.on('pageerror', lambda e:errors.append(str(e)))
        def loaded():
            page.wait_for_selector('.page-heading h1', timeout=60000)
            page.wait_for_timeout(1000)
            page.wait_for_selector('[data-testid="stApp"][data-test-script-state="notRunning"]', timeout=60000)
            assert not page.locator('[data-testid=stException]').count()
        def notices(label):
            for selector in ['.bias-notice', '.result-footer']:
                element = page.locator(selector)
                assert element.count() == 1, (label, selector)
                text = element.inner_text()
                assert '可能存在偏差' in text and '系统不设合格线' in text
                assert element.is_visible()
                assert not element.locator('xpath=ancestor::*[@data-testid="stExpander"] ').count()
            checks.append({'check':label+' both notices visible', 'status':'passed'})
        for path in ['', '/reports', '/ranking']:
            page.goto(WEB+path);loaded()
            notices('enterprise'+(path or '/matches'))
            text = page.locator('[data-testid=stMain]').inner_text().replace('系统不设合格线','')
            assert not any(word in text for word in config['banned_terms']+config['enterprise_banned_terms']), text
            checks.append({'check':'enterprise'+(path or '/matches')+' shared blacklist', 'status':'passed'})
        page.goto(WEB+'/reports');loaded()
        assert 'rubric-v0.9.6' in page.locator('[data-testid=stMain]').inner_text()
        assert '上游已对齐、未冻结' in page.locator('[data-testid=stMain]').inner_text()
        page.screenshot(path=str(ROOT/'artifacts/aligned-enterprise-report.png'),full_page=True)
        page.locator('[data-testid=stSidebar]').locator('[data-testid=stSelectbox]').first.click()
        page.get_by_role('option',name='求职者视角',exact=True).click();loaded()
        notices('candidate/matches')
        page.locator('[data-testid=stSidebar]').get_by_text('岗位对照分析',exact=True).click();loaded()
        page.get_by_role('combobox',name='当前岗位',exact=True).click()
        page.get_by_role('option',name='前端开发工程师',exact=True).click();loaded()
        # Generate using the selected concrete job and resume, not a fabricated browser result.
        page.get_by_role('button',name='开始岗位对照',exact=True).click();loaded()
        notices('candidate/fit')
        text = page.locator('[data-testid=stMain]').inner_text()
        assert '（相对 ' in text and '面试准备' not in text and '换算待确认' not in text
        page.get_by_text('量规差距说明',exact=True).click();loaded()
        text = page.locator('[data-testid=stMain]').inner_text()
        assert '量规原文' in text
        checks.append({'check':'candidate relative job and no interview prompts','status':'passed'})
        page.screenshot(path=str(ROOT/'artifacts/aligned-candidate-fit.png'),full_page=True)
        page.locator('[data-testid=stSidebar]').get_by_text('岗位参考基准',exact=True).click();loaded()
        notices('candidate/benchmark')
        browser.close()
    # Both sides retrieve the very same immutable match record.
    matches = httpx.get(API+'/matches').json()
    record = next(row for row in matches if row['candidate_owner']=='candidate:lin')
    enterprise = httpx.get(API+'/matches/'+record['id']).json()
    candidate = httpx.get(API+'/matches/'+record['id'],headers={'X-Demo-Actor':'candidate:lin'}).json()
    assert enterprise['id'] == candidate['id'] and enterprise['dimension_results'] == candidate['dimension_results']
    checks.append({'check':'both sides same match id and evidence','status':'passed'})
    assert not errors
    result = {'checks':checks,'page_errors':errors,'web_url':WEB,'api_url':API}
    (ROOT/'artifacts/alignment-browser-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
