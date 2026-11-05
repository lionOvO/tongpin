"""Local operator tool. No public endpoint can assign administrator or legacy ownership."""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.auth import Auth, PhoneInput
from app.settings import Settings
from app.db import Database, TABLES
from app.seed import ENT, PEOPLE


def promote(auth, phone):
    with auth.tx() as cx:
        account = cx.execute('SELECT * FROM accounts WHERE env=? AND phone=?', (auth.settings.env,phone)).fetchone()
        if not account:
            raise ValueError('请先通过短信验证注册工作人员的手机号。')
        cx.execute("UPDATE accounts SET role='admin' WHERE id=?", (account['id'],))
        cx.execute('DELETE FROM sessions WHERE account_id=?', (account['id'],))


def provision_admin(auth, phone):
    """A trusted server operator can invite staff without inventing credentials.

    The account has no password until the phone owner verifies an SMS code and
    sets one. Existing credentials and owners are preserved; no session is issued.
    This function is only exposed by the local CLI, never by a public endpoint.
    """
    phone = PhoneInput(phone=phone).phone
    with auth.tx() as cx:
        account = auth.account(cx, phone)
        created = account is None
        if created:
            id = str(uuid4())
            cx.execute("INSERT INTO accounts (id,env,phone,role,actor,created_at,password_hash) VALUES (?,?,?,?,?,?,NULL)",
                       (id, auth.settings.env, phone, 'admin', 'enterprise:' + id, time.time()))
        else:
            cx.execute("UPDATE accounts SET role='admin' WHERE id=?", (account['id'],))
        account = auth.account(cx, phone)
        auth.ensure_workspaces(cx, account)
        cx.execute('DELETE FROM sessions WHERE account_id=?', (account['id'],))
        return {'created': created, 'has_password': bool(account['password_hash'])}


def claim(auth, db, phone, legacy_actor):
    allowed = {ENT, *(p['actor'] for p in PEOPLE)}
    if legacy_actor not in allowed: raise ValueError('仅允许迁移明确列出的旧演示身份。')
    with auth.tx() as cx:
        account=cx.execute('SELECT * FROM accounts WHERE env=? AND phone=?', (auth.settings.env,phone)).fetchone()
        workspace=cx.execute('SELECT actor FROM account_workspaces WHERE account_id=? AND role=?', (account['id'],legacy_actor.split(':')[0])).fetchone() if account else None
    if not account: raise ValueError('请先完成手机号验证登录。')
    if not workspace: raise ValueError('目标账号没有对应的同侧工作空间。')
    account={**dict(account),'actor':workspace['actor']}
    backup_dir=auth.settings.data_dir/'backups'; backup_dir.mkdir(exist_ok=True)
    backup=backup_dir/('before-account-claim-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'.sqlite3')
    count=0
    with db.transaction() as cx:
        # Freeze writes while making a consistent backup and updating all references.
        cx.execute('BEGIN IMMEDIATE')
        with sqlite3.connect(db.path) as source, sqlite3.connect(backup) as target: source.backup(target)
        for table in TABLES:
            rows=cx.execute(f'SELECT id,owner,payload FROM {table} WHERE env=?', (auth.settings.env,)).fetchall()
            for row in rows:
                payload=json.loads(row['payload']); changed=False
                for key in ('enterprise_owner','candidate_owner'):
                    if payload.get(key)==legacy_actor: payload[key]=account['actor']; changed=True
                owner=account['actor'] if row['owner']==legacy_actor else row['owner']
                if row['owner']==legacy_actor:
                    count+=1;changed=True
                    if table=='job_profiles': payload['published']=False
                if changed: cx.execute(f'UPDATE {table} SET owner=?,payload=? WHERE id=? AND env=?', (owner,json.dumps(payload,ensure_ascii=False),row['id'],auth.settings.env))
        if cx.execute('PRAGMA foreign_key_check').fetchall(): raise ValueError('引用检查失败，已回滚。')
        db.audit('旧身份数据迁移', {'legacy_actor':legacy_actor,'count':count}, account['actor'], cx=cx)
    if auth.settings.vector:
        from app.retrieval import LocalRetrieval
        retrieval=LocalRetrieval(auth.settings)
        for resume in db.list('resumes',owner=account['actor']): retrieval.upsert(resume)
    return count,backup


def main():
    parser=argparse.ArgumentParser(description='本机账号管理；请在项目根目录运行，修改前停止正在运行的服务。')
    parser.add_argument('action', choices=['promote-admin','provision-admin','claim-legacy'])
    parser.add_argument('--phone',required=True)
    parser.add_argument('--legacy-actor',choices=[ENT,*(p['actor'] for p in PEOPLE)])
    args=parser.parse_args()
    phone=PhoneInput(phone=args.phone).phone
    settings=Settings();auth=Auth(settings)
    try:
        if args.action=='promote-admin':
            promote(auth,phone);print('已设为管理员，旧会话已撤销，请重新获取验证码登录。')
        elif args.action=='provision-admin':
            result=provision_admin(auth,phone)
            print('管理员账号已创建。首次使用短信验证码登录，再由本人设置密码。' if result['created'] else '管理员权限已设置，原密码及资料保持不变，旧会话已撤销。')
        else:
            if not args.legacy_actor: parser.error('迁移必须明确提供 --legacy-actor')
            count,backup=claim(auth,Database(settings),phone,args.legacy_actor)
            print(f'已迁移 {count} 条本人记录，岗位设为私有；备份：{backup}')
    except ValueError as error: parser.exit(1,str(error)+'\n')


if __name__=='__main__': main()
