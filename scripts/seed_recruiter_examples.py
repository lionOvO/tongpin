"""Local operator import of explicitly fictional recruiter fixtures; never available in prod or HTTP."""
import argparse
import copy
import hashlib
import json
import secrets
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4, uuid5, NAMESPACE_URL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.auth import Auth, PhoneInput
from app.models import JobInput, JobConfirmation, JobProfile
from app.passwords import hash_password, verify_password
from app.service import TalentService
from app.settings import Settings


def validate_fixture(path):
    fixture = json.loads(path.read_text(encoding='utf-8'))
    assert len(fixture['jobs']) == 4, '必须正好四个独立岗位'
    assert len({row['phone'] for row in fixture['jobs']}) == 4
    for row in fixture['jobs']:
        PhoneInput(phone=row['phone'])
        assert '虚拟测试企业' in row['company'] and '虚构' in row['address']
        profile = JobProfile.model_validate({k:row[k] for k in ('direction','education','requirements')})
        assert all(r.quote in row['jd'] for r in profile.requirements), row['title']
        JobInput(title=row['title'],jd=row['jd'],manual_profile=profile.model_dump())
    return fixture


def evidence_pdf(path, label):
    # Deliberately plain test notice, never a simulated business license or official seal.
    from pypdf import PdfWriter
    from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject
    writer=PdfWriter();page=writer.add_blank_page(width=595,height=842)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject()
    stream.set_data(('BT /F1 16 Tf 50 760 Td (LOCAL DEMO ONLY - FICTIONAL COMPANY) Tj '
        '0 -35 Td (NOT A BUSINESS LICENSE OR AUTHORIZATION) Tj '
        '0 -35 Td (NO REAL COMPANY VERIFICATION PERFORMED) Tj '
        f'0 -35 Td (Fixture: {label}) Tj ET').encode('ascii'))
    page[NameObject('/Contents')]=writer._add_object(stream)
    writer.add_metadata({'/Title':'SYNTHETIC TEST NOTICE - NOT VALID CREDENTIALS'})
    with path.open('wb') as handle: writer.write(handle)


def seed_examples(settings, fixture_path):
    if settings.env not in {'demo','dev'}:
        raise ValueError('虚拟招聘账号只能导入 demo/dev 环境，禁止导入 prod。')
    fixture=validate_fixture(fixture_path)
    digest=hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    manifest_path=settings.data_dir/'operator_seeds'/(fixture['seed_id']+'.json')
    settings.data_dir.mkdir(parents=True,exist_ok=True)
    auth=Auth(settings)
    local_settings=copy.copy(settings);local_settings.llm_mode='demo';local_settings.vector=False
    service=TalentService(local_settings)
    service.enterprise_owner_verified=auth.enterprise_owner_verified
    service.enterprise_company_name=auth.enterprise_company_name
    service.enterprise_hiring_enabled=lambda actor: auth.actor_active(actor) and auth.enterprise_owner_verified(actor)
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest['fixture_sha256']!=digest or manifest['env']!=settings.env:
            raise ValueError('已有导入记录与当前内容不符；停止以避免覆盖旧账号。')
    else:
        with auth.tx() as cx:
            if any(auth.account(cx,row['phone']) for row in fixture['jobs']):
                raise ValueError('测试登录标识已存在，停止；不会覆盖已有账号。')
        password='Tp!'+secrets.token_urlsafe(12)
        accounts=[]
        for row in fixture['jobs']:
            account_id=str(uuid4())
            accounts.append({'phone':row['phone'],'company':row['company'],'account_id':account_id,
                             'actor':'enterprise:'+account_id,'job_id':None,'password':password})
        manifest={'seed_id':fixture['seed_id'],'env':settings.env,'fixture_sha256':digest,
            'created_at':datetime.now(timezone.utc).isoformat(),'state':'pending','accounts':accounts}
        manifest_path.parent.mkdir(parents=True,exist_ok=True)
        with manifest_path.open('x',encoding='utf-8') as output: json.dump(manifest,output,ensure_ascii=False,indent=2)
    # SQLite online backup also includes committed WAL pages. Never copy open DB files directly.
    backup=settings.data_dir/'backups'/('before-recruiter-examples-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True,exist_ok=False)
    for source in (auth.path,service.db.path):
        with sqlite3.connect(source) as src, sqlite3.connect(backup/source.name) as dst: src.backup(dst)
    manifest.setdefault('backups',[]).append(str(backup))
    for row,account in zip(fixture['jobs'],manifest['accounts']):
        with auth.tx() as cx:
            existing=auth.account(cx,row['phone'])
            if existing and (existing['id']!=account['account_id'] or existing['role']!='enterprise'
                    or not verify_password(account['password'],existing['password_hash'])):
                raise ValueError('已有账号与导入记录不符，停止；未覆盖该账号。')
            if not existing:
                cx.execute('INSERT INTO accounts (id,env,phone,role,actor,created_at,password_hash) VALUES (?,?,?,?,?,?,?)',
                    (account['account_id'],settings.env,row['phone'],'enterprise',account['actor'],time.time(),hash_password(account['password'])))
                existing=auth.account(cx,row['phone'])
            auth.ensure_workspaces(cx,existing)
            sid=str(uuid5(NAMESPACE_URL,fixture['seed_id']+':'+settings.env+':'+row['phone']))
            latest=auth.verification.latest(cx,account['account_id'])
            if latest and latest['id']!=sid:
                raise ValueError('此账号已有其他资质流程，停止而不修改其审核状态。')
            if not latest:
                folder=auth.verification.folder/sid;folder.mkdir(parents=True,exist_ok=True)
                for kind in ('license','authorization'): evidence_pdf(folder/(kind+'.pdf'),row['phone'][-4:]+'-'+kind)
                cx.execute('''INSERT INTO enterprise_submissions (id,account_id,company_name,credit_code,
                    legal_representative,contact_name,license_name,authorization_name,license_file,
                    authorization_file,status,reason,created_at,reviewed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (sid,account['account_id'],row['company'],'DEMO-20261015-'+row['phone'][-4:],
                     '虚构测试法人',row['contact'],'虚拟测试说明.pdf','虚拟测试说明.pdf','license.pdf','authorization.pdf',
                     'approved','本机维护导入的合成测试企业，仅在非生产环境开放招聘测试；未进行真实企业资质核验。',time.time(),time.time()))
        jobs=[j for j in service.db.list('job_profiles',owner=account['actor']) if j.get('operator_seed_id')==fixture['seed_id']]
        if len(jobs)>1: raise ValueError('发现重复导入的岗位，请先核查。')
        if not jobs:
            profile={k:row[k] for k in ('direction','education','requirements')}
            text=f"【本地虚拟招聘测试】\n企业：{row['company']}\n联系人：{row['contact']}\n办公地点：{row['address']}\n此岗位用于同频功能演示，不代表真实招聘。\n\n{row['jd']}"
            job=service.create_job(JobInput(title=row['title'],jd=text,manual_profile=profile,data_origin='synthetic'),account['actor'])
            service.db.update('job_profiles',job['id'],{'operator_seed_id':fixture['seed_id'],'fixture_source':row['source']})
            job=service.confirm_job(job['id'],JobConfirmation(profile=JobProfile.model_validate(profile),expected_version=job['version']),account['actor'])
            assert auth.enterprise_owner_verified(account['actor'])
            service.db.update('job_profiles',job['id'],{'published':True})
            service.db.audit('合成测试岗位发布',{'job_id':job['id'],'seed_id':fixture['seed_id'],
                'fictional_company':True,'real_verification':False},account['actor'])
        else:
            job=jobs[0]
            if job['data_origin']!='synthetic' or job['status']!='已确认' or not job.get('published'):
                raise ValueError('已有测试岗位状态发生变化，不自动覆盖修改。')
        account['job_id']=job['id']
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest['state']='complete'
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest_path,manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='仅本地 demo/dev：导入四个明确标注为虚构的招聘测试账号和岗位；不会发送短信或调用模型。')
    parser.add_argument('--validate-only',action='store_true')
    args=parser.parse_args()
    fixture_path=ROOT/'scripts'/'fixtures'/'recruiter_examples_20261015.json'
    if args.validate_only:
        fixture=validate_fixture(fixture_path);print(f"已验证 {len(fixture['jobs'])} 组岗位内容与原文引用；未写入数据。")
    else:
        path,manifest=seed_examples(Settings(),fixture_path)
        print(json.dumps({'state':manifest['state'],'credentials_file':str(path),
            'accounts':[{k:row[k] for k in ('phone','company','job_id')} for row in manifest['accounts']]},ensure_ascii=False,indent=2))
