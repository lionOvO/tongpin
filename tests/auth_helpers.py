"""No network or shared codes in app code: this SMS transport exists only in tests."""
import secrets
import time
from uuid import uuid4


def approve_enterprise_fixture(client, user):
    """Synthetic approved organization for legacy business scenarios, test code only.

    Real submission and human-admin approval are exercised in test_enterprise_verification.py.
    """
    auth=client.app.state.auth
    with auth.tx() as cx:
        if auth.verification.status(cx,user['id']) != 'approved':
            cx.execute('''INSERT INTO enterprise_submissions (id,account_id,company_name,credit_code,
                legal_representative,contact_name,license_name,authorization_name,license_file,
                authorization_file,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (str(uuid4()),user['id'],'合成测试企业','91310115MA1K123456','合成法人','合成招聘人','test.pdf','test.pdf','license.pdf','authorization.pdf','approved',time.time()))
    response=client.post('/auth/workspace',json={'role':'enterprise'})
    assert response.status_code==200,response.text
    client.headers['X-CSRF-Token']=response.json()['csrf_token']
    return response.json()['user']


class FakeSMS:
    def __init__(self):
        self.codes = {}
        self.calls = []

    def missing(self): return []

    def send(self, phone):
        self.codes[phone] = f"{secrets.randbelow(1000000):06d}"
        self.calls.append(phone)

    def verify(self, phone, code):
        if self.codes.get(phone) == code:
            del self.codes[phone]
            return True
        return False


def sign_in(client, phone, role="candidate"):
    with client.app.state.auth.tx() as cx:
        exists = cx.execute('SELECT id,role FROM accounts WHERE env=? AND phone=?', (client.app.state.auth.settings.env,phone)).fetchone()
    staff = bool(exists and exists['role'] == 'admin' and role == 'enterprise')
    client.headers['X-Session-Scope'] = 'admin' if staff else 'user'
    purpose = 'login' if exists else 'register'
    response = client.post('/auth/sms/send', json={"phone": phone, "purpose": purpose})
    assert response.status_code == 200, response.text
    code = client.app.state.auth.sms.codes[phone]
    payload = {"phone": phone, "code": code, "role": role}
    if not exists: payload['password'] = 'Scenario-password-2026'
    response = client.post('/auth/admin/login/phone' if staff else '/auth/login/phone' if exists else '/auth/register', json=payload)
    assert response.status_code == 200, response.text
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    user=response.json()['user']
    return approve_enterprise_fixture(client,user) if role=='enterprise' and not staff else user
