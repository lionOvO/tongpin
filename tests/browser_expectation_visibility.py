"""Run against a fresh serve_expectation_preview.py plus Vite on port 8529."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
root=Path(os.getenv('EXPECTATION_QA_OUT','artifacts/expectation-visibility-final'));root.mkdir(parents=True,exist_ok=True)
base=os.getenv('EXPECTATION_QA_URL','http://127.0.0.1:8529')
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
 errors=[]
 def login(phone,enterprise=False):
  page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(base+'/login');page.locator('#auth-phone').fill(phone);page.locator('#auth-password').fill('Scenario-password-2026')
  if enterprise:page.get_by_role('radio',name='招聘方',exact=True).check()
  page.locator('form button.primary').click();page.wait_for_url('**/workspace');return page
 candidate=login('13800000980')
 candidate.goto(base+'/preferences')
 fields=candidate.locator('.preference-dimension');expect(fields).to_have_count(3)
 for field in fields.all():field.locator('input[type=radio]').first.check()
 visibility=candidate.get_by_role('group',name='谁可以看到我的期待',exact=True)
 visibility.locator('input').nth(0).check()
 expect(candidate.get_by_role('button',name='保存我的期待',exact=True)).to_be_enabled()
 with candidate.expect_response(lambda r:'/preferences/submit' in r.url) as saved:candidate.get_by_role('button',name='保存我的期待',exact=True).click()
 assert saved.value.json()['share_with_counterparty'] is False
 expect(candidate.get_by_role('button',name='保存我的期待',exact=True)).to_be_enabled()
 visibility.locator('input').nth(1).check()
 with candidate.expect_response(lambda r:'/preferences/submit' in r.url) as saved:candidate.get_by_role('button',name='保存我的期待',exact=True).click()
 assert saved.value.json()['share_with_counterparty'] is True
 visibility.scroll_into_view_if_needed();candidate.screenshot(path=str(root/'desktop-settings.png'))
 for width in [390,360]:
  candidate.set_viewport_size({'width':width,'height':844});candidate.wait_for_timeout(400);visibility.scroll_into_view_if_needed()
  assert candidate.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
  assert visibility.evaluate('(el)=>el.scrollWidth<=el.clientWidth'),width
  candidate.screenshot(path=str(root/f'mobile-{width}-settings.png'))
 candidate.set_viewport_size({'width':1440,'height':1000});candidate.wait_for_timeout(400)
 candidate.goto(base+'/jobs');candidate.get_by_role('button').filter(has_text='公开设置验证岗位 · 合成').first.click()
 candidate.get_by_role('button',name='投递这个岗位',exact=True).click()
 dialog=candidate.get_by_role('dialog');expect(dialog.get_by_role('checkbox')).to_have_count(1)
 expect(dialog.get_by_text('求职期待自动沿用“我的期待”中的公开设置。',exact=False)).to_be_visible()
 dialog.get_by_role('checkbox').check();candidate.screenshot(path=str(root/'apply-without-repeated-consent.png'))
 with candidate.expect_response(lambda r:r.url.endswith('/api/applications') and r.request.method=='POST') as applied:
  dialog.get_by_role('button',name='确认授权并投递',exact=True).click()
 application=applied.value.json();assert application['candidate_preferences'] is not None
 assert 'share_preferences' not in applied.value.request.post_data_json
 appid=application['id']
 enterprise=login('13800000991',True)
 enterprise.goto(base+'/preferences')
 expect(enterprise.locator('.preference-dimension')).to_have_count(3)
 for field in enterprise.locator('.preference-dimension').all():field.locator('input[type=radio]').first.check()
 team=enterprise.get_by_role('group',name='谁可以看到我的期待',exact=True);team.locator('input').nth(1).check()
 with enterprise.expect_response(lambda r:'/preferences/submit' in r.url) as saved:enterprise.get_by_role('button',name='保存我的期待',exact=True).click()
 assert saved.value.json()['share_with_counterparty'] is True
 with enterprise.expect_response(lambda r:r.url.endswith('/applications/'+appid)) as detail:enterprise.goto(base+'/applications?application='+appid)
 assert detail.value.json()['candidate_preferences'] is not None
 assert detail.value.json()['preference_comparison'] is not None
 expect(enterprise.get_by_role('button',name='同步我的最新期待',exact=True)).to_have_count(0)
 candidate.goto(base+'/preferences');visibility=candidate.get_by_role('group',name='谁可以看到我的期待',exact=True)
 visibility.locator('input').first.check()
 with candidate.expect_response(lambda r:'/preferences/submit' in r.url) as saved:candidate.get_by_role('button',name='保存我的期待',exact=True).click()
 assert saved.value.json()['share_with_counterparty'] is False
 with enterprise.expect_response(lambda r:r.url.endswith('/applications/'+appid)) as detail:enterprise.reload()
 assert detail.value.json()['candidate_preferences'] is None
 assert detail.value.json()['preference_comparison'] is None
 expect(candidate.get_by_role('radio',name='仅自己可见',exact=False)).to_be_checked()
 enterprise.goto(base+'/preferences');team=enterprise.get_by_role('group',name='谁可以看到我的期待',exact=True)
 expect(team.get_by_text('公开给应聘者',exact=True)).to_be_visible()
 # Private expectations must not block the human invitation and chat flow.
 enterprise.goto(base+'/applications?application='+appid)
 enterprise.get_by_role('button',name='邀请沟通',exact=True).click()
 action=enterprise.get_by_role('dialog');action.locator('textarea').fill('希望了解你在项目中负责的接口开发。')
 action.get_by_role('button',name='邀请沟通',exact=True).click();expect(action).not_to_be_visible()
 candidate.goto(base+'/applications?application='+appid)
 candidate.get_by_role('button',name='接受沟通邀请',exact=True).click()
 action=candidate.get_by_role('dialog');action.get_by_role('button',name='接受沟通邀请',exact=True).click();expect(action).not_to_be_visible()
 candidate.goto(base+'/messages?application='+appid)
 candidate.locator('#human-chat-input').fill('你好，我负责订单接口开发和测试。')
 candidate.get_by_role('button',name='发送消息',exact=True).click()
 enterprise.goto(base+'/messages?application='+appid)
 expect(enterprise.get_by_role('log').get_by_text('你好，我负责订单接口开发和测试。',exact=True)).to_be_visible()
 enterprise.locator('#human-chat-input').fill('收到，我们可以进一步聊聊实现过程。')
 enterprise.get_by_role('button',name='发送消息',exact=True).click()
 expect(enterprise.get_by_role('log').get_by_text('收到，我们可以进一步聊聊实现过程。',exact=True)).to_be_visible()
 # Changes are picked up by a still-open conversation, even without an application version change.
 candidate.goto(base+'/preferences');visibility=candidate.get_by_role('group',name='谁可以看到我的期待',exact=True)
 visibility.locator('input').nth(1).check()
 with candidate.expect_response(lambda r:'/preferences/submit' in r.url):candidate.get_by_role('button',name='保存我的期待',exact=True).click()
 with enterprise.expect_response(lambda r:r.url.endswith('/applications/'+appid)) as detail:enterprise.get_by_role('button',name='刷新消息',exact=True).click()
 assert detail.value.json()['candidate_preferences'] is not None and detail.value.json()['preference_comparison'] is not None
 visibility.locator('input').first.check()
 with candidate.expect_response(lambda r:'/preferences/submit' in r.url):candidate.get_by_role('button',name='保存我的期待',exact=True).click()
 with enterprise.expect_response(lambda r:r.url.endswith('/applications/'+appid)) as detail:enterprise.get_by_role('button',name='刷新消息',exact=True).click()
 assert detail.value.json()['candidate_preferences'] is None and detail.value.json()['preference_comparison'] is None
 expect(enterprise.locator('.conversation-expectation p').filter(has_text='求职者').first).to_contain_text('尚未共享')
 for width in [390,360]:
  enterprise.set_viewport_size({'width':width,'height':844})
  enterprise.wait_for_timeout(300)
  assert enterprise.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
  enterprise.screenshot(path=str(root/f'mobile-{width}-chat.png'))
 assert not errors,errors
 results={'private_save':True,'public_save':True,'apply_checkbox_count':1,'automatic_publication':True,'existing_application_private':True,'mobile_widths':[390,360],'private_invite_accept_chat':True,'page_errors':errors}
 (root/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(results,ensure_ascii=False));browser.close()
