from fastapi.testclient import TestClient
import pytest
from app.main import create_app
from app.settings import Settings
from auth_helpers import FakeSMS, sign_in
from scripts.manage_accounts import promote, claim, provision_admin


def test_legacy_data_is_not_auto_claimed_and_explicit_migration_preserves_snapshots(tmp_path):
    settings=Settings(data_dir=tmp_path,env='demo',auto_seed=True)
    app=create_app(settings);app.state.auth.sms=FakeSMS()
    with TestClient(app) as client:
        user=sign_in(client,'13800000201','enterprise')
        assert client.get('/jobs').json()==[]
        db=app.state.service.db
        legacy_ids={j['id'] for j in db.list('job_profiles',owner='enterprise:demo')}
        report=db.list('ability_reports',owner='enterprise:demo')[0]
        count,backup=claim(app.state.auth,db,'13800000201','enterprise:demo')
        assert count>0 and backup.is_file()
        rows=client.get('/jobs').json()
        assert {j['id'] for j in rows}==legacy_ids and all(not j['published'] for j in rows)
        migrated=db.get('ability_reports',report['id'])
        assert migrated['owner']==user['actor'] and migrated['rubric_snapshot']==report['rubric_snapshot']
        assert all(m['enterprise_owner']==user['actor'] for m in client.get('/matches').json())
        with db.transaction() as cx: assert not cx.execute('PRAGMA foreign_key_check').fetchall()


def test_local_admin_promotion_revokes_sessions_and_requires_existing_account(tmp_path):
    app=create_app(Settings(data_dir=tmp_path,env='demo',auto_seed=False));app.state.auth.sms=FakeSMS()
    with TestClient(app) as enterprise,TestClient(app) as candidate:
        sign_in(enterprise,'13800000201','enterprise');sign_in(candidate,'13800000202','candidate')
        with pytest.raises(ValueError): promote(app.state.auth,'13800000209')
        promote(app.state.auth,'13800000201')
        assert enterprise.get('/auth/me').status_code==401
        with app.state.auth.tx() as cx:cx.execute('DELETE FROM codes');cx.execute('DELETE FROM limits')
        user=sign_in(enterprise,'13800000201','enterprise')
        assert user['role']=='admin'
        assert enterprise.get('/config/packs').status_code==200
        assert enterprise.post('/demo/seed').status_code==200
        assert len(enterprise.get('/jobs').json())==3
        assert all(not j['published'] for j in enterprise.get('/jobs').json())
        assert candidate.get('/jobs').json()==[]
        assert candidate.get('/resumes').json()==[]


def test_operator_provisions_staff_without_password_or_session_and_requires_sms(tmp_path):
    app=create_app(Settings(data_dir=tmp_path,env='demo',auto_seed=False));app.state.auth.sms=FakeSMS()
    auth=app.state.auth
    phone='13800000205'
    assert provision_admin(auth,phone)=={'created':True,'has_password':False}
    with auth.tx() as cx:
        account=auth.account(cx,phone)
        id=account['id']
        assert account['role']=='admin' and account['password_hash'] is None
        assert cx.execute('SELECT COUNT(*) FROM sessions WHERE account_id=?',(id,)).fetchone()[0]==0
        assert cx.execute('SELECT COUNT(*) FROM account_workspaces WHERE account_id=?',(id,)).fetchone()[0]==2
    assert not auth.sms.calls
    with TestClient(app) as client:
        assert client.get('/admin/overview').status_code==401
        assert client.post('/auth/admin/login/password',json={'phone':phone,'password':'Any-default-password'}).status_code==400
        assert client.post('/auth/admin/login/phone',json={'phone':phone,'code':'000000'}).status_code==400
        assert client.post('/auth/sms/send',json={'phone':phone,'purpose':'login'}).status_code==200
        result=client.post('/auth/admin/login/phone',json={'phone':phone,'code':auth.sms.codes[phone]})
        assert result.status_code==200 and result.json()['user']['role']=='admin'
        assert result.json()['user']['has_password'] is False
        client.headers['X-CSRF-Token']=result.json()['csrf_token']
        assert client.get('/admin/overview').status_code==200
        # The staff member sets the first password only after a second verified SMS.
        with auth.tx() as cx:cx.execute('DELETE FROM limits')
        assert client.post('/auth/sms/send',json={'phone':phone,'purpose':'reset'}).status_code==200
        result=client.post('/auth/admin/password/reset',json={'phone':phone,'code':auth.sms.codes[phone],'password':'Own-staff-password-2026'})
        assert result.status_code==200 and result.json()['user']['has_password'] is True
        result=client.post('/auth/admin/login/password',json={'phone':phone,'password':'Own-staff-password-2026'})
        assert result.status_code==200 and result.json()['user']['id']==id


def test_repeated_staff_provision_keeps_credentials_owners_and_other_users(tmp_path):
    app=create_app(Settings(data_dir=tmp_path,env='demo',auto_seed=False));app.state.auth.sms=FakeSMS()
    auth=app.state.auth
    with TestClient(app) as staff,TestClient(app) as other:
        original=sign_in(staff,'13800000206','candidate')
        sign_in(other,'13800000207','candidate')
        with auth.tx() as cx:
            before=dict(auth.account(cx,'13800000206'))
            owners=cx.execute('SELECT role,actor FROM account_workspaces WHERE account_id=? ORDER BY role',(original['id'],)).fetchall()
        for _ in range(2):assert provision_admin(auth,'13800000206')=={'created':False,'has_password':True}
        with auth.tx() as cx:
            after=dict(auth.account(cx,'13800000206'))
            assert {k:v for k,v in before.items() if k!='role'}=={k:v for k,v in after.items() if k!='role'}
            assert [tuple(r) for r in owners]==[tuple(r) for r in cx.execute('SELECT role,actor FROM account_workspaces WHERE account_id=? ORDER BY role',(original['id'],))]
        assert staff.get('/auth/me').status_code==401 and other.get('/auth/me').status_code==200
        assert other.get('/admin/overview').status_code==401
