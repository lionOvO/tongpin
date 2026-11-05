"""Phone accounts and revocable cookie sessions, separate from business records."""
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import Request, Response
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Literal
from .errors import DomainError
from .sms import AliyunSMS
from .passwords import hash_password, verify_password
from .enterprise_verification import EnterpriseVerification

COOKIE = "tongpin_session"
ADMIN_COOKIE = "tongpin_admin_session"


class PhoneInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(pattern=r"^1[3-9][0-9]{9}$")

    @field_validator("phone", mode="before")
    @classmethod
    def trim_phone(cls, value):
        return value.strip() if isinstance(value, str) else value


class SmsInput(PhoneInput):
    purpose: Literal["login", "register", "reset"] = "login"


class PhoneLogin(PhoneInput):
    code: str = Field(pattern=r"^[0-9]{6}$")
    role: Literal["enterprise", "candidate"] | None = None


class PasswordInput(PhoneInput):
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("密码不能全为空格")
        return value


class Registration(PasswordInput):
    code: str = Field(pattern=r"^[0-9]{6}$")
    role: Literal["enterprise", "candidate"]


class PasswordLogin(PasswordInput):
    role: Literal["enterprise", "candidate"] | None = None


class WorkspaceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["enterprise", "candidate"]


class PasswordReset(PasswordInput):
    code: str = Field(pattern=r"^[0-9]{6}$")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Auth:
    def __init__(self, settings):
        self.settings = settings
        self.path = settings.data_dir / "auth.sqlite3"
        self.lock = threading.RLock()
        self.sms = AliyunSMS(settings)
        with self.tx() as cx:
            cx.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, env TEXT NOT NULL, phone TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('enterprise','candidate','admin')),
                    actor TEXT NOT NULL UNIQUE, created_at REAL NOT NULL, UNIQUE(env,phone));
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
                    csrf TEXT NOT NULL, expires_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
                CREATE TABLE IF NOT EXISTS codes (
                    env TEXT NOT NULL, phone TEXT NOT NULL, sent_at REAL NOT NULL,
                    expires_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    ready INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(env,phone));
                CREATE TABLE IF NOT EXISTS limits (
                    key TEXT PRIMARY KEY, count INTEGER NOT NULL, resets_at REAL NOT NULL);
            """)
            # Additive migration: preserve all existing account IDs, roles and data owners.
            if "password_hash" not in {r["name"] for r in cx.execute("PRAGMA table_info(accounts)")}:
                cx.execute("ALTER TABLE accounts ADD COLUMN password_hash TEXT")
            if "disabled" not in {r["name"] for r in cx.execute("PRAGMA table_info(accounts)")}:
                cx.execute("ALTER TABLE accounts ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0")
            if "purpose" not in {r["name"] for r in cx.execute("PRAGMA table_info(codes)")}:
                cx.execute("ALTER TABLE codes ADD COLUMN purpose TEXT NOT NULL DEFAULT 'login'")
            EnterpriseVerification.setup(cx)
            cx.execute("""CREATE TABLE IF NOT EXISTS account_workspaces (
                account_id TEXT NOT NULL REFERENCES accounts(id),
                role TEXT NOT NULL CHECK(role IN ('enterprise','candidate')),
                actor TEXT NOT NULL UNIQUE, PRIMARY KEY(account_id,role))""")
            if "workspace_role" not in {r["name"] for r in cx.execute("PRAGMA table_info(sessions)")}:
                cx.execute("ALTER TABLE sessions ADD COLUMN workspace_role TEXT CHECK(workspace_role IN ('enterprise','candidate'))")
                # Existing sessions retain their original workspace; no business records move.
                cx.execute("""UPDATE sessions SET workspace_role=(SELECT CASE WHEN role='candidate'
                    THEN 'candidate' ELSE 'enterprise' END FROM accounts WHERE id=sessions.account_id)""")
            if "session_scope" not in {r["name"] for r in cx.execute("PRAGMA table_info(sessions)")}:
                cx.execute("ALTER TABLE sessions ADD COLUMN session_scope TEXT NOT NULL DEFAULT 'user' CHECK(session_scope IN ('user','admin'))")
                # Legacy staff tokens must not keep privileged access through the user cookie.
                cx.execute("""UPDATE sessions SET session_scope='admin' WHERE workspace_role='enterprise'
                    AND account_id IN (SELECT id FROM accounts WHERE role='admin')""")
            for account in cx.execute("SELECT * FROM accounts").fetchall():
                self.ensure_workspaces(cx, account)
                if account["role"] != "admin" and EnterpriseVerification.status(cx, account["id"]) != "approved":
                    cx.execute("UPDATE sessions SET workspace_role='candidate' WHERE account_id=? AND workspace_role='enterprise'", (account["id"],))
        self.verification = EnterpriseVerification(self)

    @contextmanager
    def tx(self):
        with self.lock:
            cx = sqlite3.connect(self.path, timeout=20)
            cx.row_factory = sqlite3.Row
            cx.execute("PRAGMA foreign_keys=ON")
            cx.execute("BEGIN IMMEDIATE")
            try:
                yield cx
                cx.commit()
            except Exception:
                cx.rollback()
                raise
            finally:
                cx.close()

    def origin(self, request):
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != request.headers.get("host", "").lower():
                raise DomainError("ORIGIN_DENIED", "请从同频页面发起操作。", 403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise DomainError("ORIGIN_DENIED", "请从同频页面发起操作。", 403)

    def limit(self, key, maximum, seconds):
        stamp = time.time()
        blocked = False
        with self.tx() as cx:
            cx.execute("DELETE FROM limits WHERE resets_at<=?", (stamp,))
            key = digest(self.settings.env + ":" + key)
            row = cx.execute("SELECT * FROM limits WHERE key=?", (key,)).fetchone()
            if row and row["count"] >= maximum:
                blocked = True
            elif row:
                cx.execute("UPDATE limits SET count=count+1 WHERE key=?", (key,))
            else:
                cx.execute("INSERT INTO limits VALUES (?,?,?)", (key, 1, stamp + seconds))
        if blocked:
            raise DomainError("AUTH_RATE_LIMIT", "操作过于频繁，请稍后再试。", 429)

    def send(self, data, request):
        self.origin(request)
        if self.sms.missing():
            raise DomainError("SMS_NOT_CONFIGURED", "短信服务尚未配置，请联系管理员完成短信配置。", 503)
        ip = request.client.host if request.client else "unknown"
        self.limit("send-ip:" + ip, 10, 600)
        self.limit("send-phone-hour:" + data.phone, 5, 3600)
        self.limit("send-phone-day:" + data.phone, 20, 86400)
        stamp = time.time()
        with self.tx() as cx:
            cx.execute("DELETE FROM codes WHERE expires_at<=?", (stamp,))
            row = cx.execute("SELECT * FROM codes WHERE env=? AND phone=?", (self.settings.env, data.phone)).fetchone()
            if row and stamp - row["sent_at"] < 60:
                raise DomainError("SMS_COOLDOWN", "请等待 60 秒后再获取验证码。", 429)
            cx.execute("INSERT OR REPLACE INTO codes (env,phone,sent_at,expires_at,attempts,ready,purpose) VALUES (?,?,?,?,0,0,?)", (self.settings.env, data.phone, stamp, stamp + 300, data.purpose))
        try:
            self.sms.send(data.phone)
        except Exception:
            # Keep cooldown on uncertain network failures; never automatically resend paid SMS.
            raise
        with self.tx() as cx:
            cx.execute("UPDATE codes SET ready=1 WHERE env=? AND phone=? AND sent_at=?", (self.settings.env, data.phone, stamp))
        return {"message": "验证码已发送，请查看手机短信。", "expires_in": 300, "retry_after": 60}

    @staticmethod
    def public(account):
        phone = account["phone"]
        return {"id": account["id"], "actor": account["actor"], "role": account["role"], "workspace_role": account["workspace_role"], "session_scope": account["session_scope"], "available_roles": ["enterprise", "candidate"] if account["enterprise_status"] == "approved" else ["candidate"], "enterprise_status": account["enterprise_status"], "name": phone[:3] + "****" + phone[-4:], "has_password": bool(account["password_hash"])}

    @staticmethod
    def request_scope(request):
        path=request.url.path
        if path == '/admin' or path.startswith(('/admin/', '/auth/admin/', '/enterprise-reviews')):
            return 'admin'
        return 'admin' if request.headers.get('x-session-scope') == 'admin' else 'user'

    @staticmethod
    def request_tab(request, header="x-session-tab"):
        value = request.headers.get(header)
        if value is None:
            return None  # Legacy API clients retain their original cookie contract.
        try:
            if len(value) != 36 or str(UUID(value)) != value.lower():
                raise ValueError()
            return UUID(value).hex
        except (ValueError, AttributeError):
            raise DomainError("SESSION_TAB_INVALID", "页面会话标识无效，请重新打开页面。", 400)

    def cookie_name(self, scope, tab=None):
        name = ADMIN_COOKIE if scope == 'admin' else COOKIE
        # HTTP cannot overwrite an existing Secure cookie from the HTTPS site.
        # Keep both transports distinct so switching does not silently break login.
        if self.settings.env == 'prod' and not self.settings.session_cookie_secure:
            name += '_http'
        return name + '_' + tab if tab else name

    def cookie(self, response, token, scope='user', tab=None):
        response.set_cookie(self.cookie_name(scope, tab), token, max_age=43200, httponly=True, secure=self.settings.session_cookie_secure, samesite="strict", path="/")
        response.headers["Cache-Control"] = "no-store"

    def verify_code(self, data, request, purpose):
        self.origin(request)
        ip = request.client.host if request.client else "unknown"
        self.limit("verify-ip:" + ip, 40, 600)
        stamp = time.time()
        # Commit the attempt before contacting provider: wrong codes and provider errors count.
        with self.tx() as cx:
            row = cx.execute("SELECT * FROM codes WHERE env=? AND phone=?", (self.settings.env, data.phone)).fetchone()
            if not row or row["purpose"] != purpose or row["expires_at"] <= stamp or row["attempts"] >= 5 or not row["ready"]:
                raise DomainError("SMS_CODE_INVALID", "验证码已失效或尝试次数过多，请重新获取。", 400)
            cx.execute("UPDATE codes SET attempts=attempts+1,ready=0 WHERE env=? AND phone=?", (self.settings.env, data.phone))
        try:
            passed = self.sms.verify(data.phone, data.code)
        except Exception:
            with self.tx() as cx:
                cx.execute("UPDATE codes SET ready=1 WHERE env=? AND phone=? AND sent_at=?", (self.settings.env, data.phone, row["sent_at"]))
            raise
        with self.tx() as cx:
            fresh = cx.execute("SELECT * FROM codes WHERE env=? AND phone=?", (self.settings.env, data.phone)).fetchone()
            if not fresh or fresh["sent_at"] != row["sent_at"] or fresh["expires_at"] <= time.time():
                raise DomainError("SMS_CODE_INVALID", "验证码已失效，请重新获取。", 400)
            if not passed:
                cx.execute("UPDATE codes SET ready=1 WHERE env=? AND phone=?", (self.settings.env, data.phone))
            else:
                cx.execute("DELETE FROM codes WHERE env=? AND phone=?", (self.settings.env, data.phone))
        if not passed:
            raise DomainError("SMS_CODE_INVALID", "验证码不正确或已失效，请检查后重新输入。", 400)

    def account(self, cx, phone):
        return cx.execute("SELECT * FROM accounts WHERE env=? AND phone=?", (self.settings.env, phone)).fetchone()

    @staticmethod
    def ensure_workspaces(cx, account):
        primary = "candidate" if account["role"] == "candidate" else "enterprise"
        for role in ("enterprise", "candidate"):
            actor = account["actor"] if role == primary else role + ":" + account["id"]
            cx.execute("INSERT INTO account_workspaces (account_id,role,actor) VALUES (?,?,?) ON CONFLICT(account_id,role) DO NOTHING", (account["id"], role, actor))

    def workspace(self, cx, account, role, scope='user'):
        if scope == 'admin' and (account['role'] != 'admin' or role != 'enterprise'):
            raise DomainError('ADMIN_REQUIRED', '请使用平台工作人员账号登录管理端。', 403)
        status = "approved" if account["role"] == "admin" else EnterpriseVerification.status(cx, account["id"])
        if role == "enterprise" and status != "approved":
            raise DomainError("ENTERPRISE_VERIFICATION_REQUIRED", "请先提交企业资质，管理员核验通过后才能进入招聘方空间。", 403)
        row = cx.execute("SELECT actor FROM account_workspaces WHERE account_id=? AND role=?", (account["id"], role)).fetchone()
        if not row:
            raise DomainError("WORKSPACE_DENIED", "当前账号没有此工作空间。", 403)
        return {**dict(account), "account_role": account["role"], "actor": row["actor"], "workspace_role": role, "enterprise_status": status,
                "session_scope":scope, "role": "admin" if scope == 'admin' else role}

    def issue(self, cx, account, request, role=None, scope='user', target_tab=None):
        stamp = time.time()
        if account["disabled"]:
            raise DomainError("ACCOUNT_DISABLED", "账号已被平台暂停使用，请联系平台工作人员。", 403)
        role = role or ("candidate" if account["role"] == "candidate" else "enterprise")
        if role == "enterprise" and account["role"] != "admin" and EnterpriseVerification.status(cx, account["id"]) != "approved":
            role = "candidate"
        user = self.workspace(cx, account, role, scope)
        tab = self.request_tab(request) if target_tab is None else target_tab
        user["_session_tab"] = tab
        # A forked tab/workspace replaces only its target cookie, never the source.
        old = request.cookies.get(self.cookie_name(scope, tab), "")
        cx.execute("DELETE FROM sessions WHERE (token_hash=? AND session_scope=?) OR expires_at<=?", (digest(old), scope, stamp))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        cx.execute("INSERT INTO sessions (token_hash,account_id,csrf,expires_at,workspace_role,session_scope) VALUES (?,?,?,?,?,?)", (digest(token), account["id"], csrf, stamp + 43200, role, scope))
        return user, token, csrf

    def result(self, account, token, csrf, response):
        self.cookie(response, token, account['session_scope'], account.get('_session_tab'))
        return {"user": self.public(account), "csrf_token": csrf}

    def login(self, data, request, response, admin_only=False):
        self.verify_code(data, request, "login")
        with self.tx() as cx:
            account = self.account(cx, data.phone)
            if not account:
                raise DomainError("ACCOUNT_NOT_REGISTERED", "该手机号尚未注册，请先完成验证码注册并设置密码。", 400)
            if admin_only and account["role"] != "admin":
                raise DomainError("ADMIN_REQUIRED", "此账号没有平台管理权限，请使用工作人员账号。", 403)
            user, token, csrf = self.issue(cx, account, request, "enterprise" if admin_only else data.role, 'admin' if admin_only else 'user')
        return self.result(user, token, csrf, response)

    def register(self, data, request, response):
        self.verify_code(data, request, "register")
        encoded = hash_password(data.password)
        with self.tx() as cx:
            if self.account(cx, data.phone):
                raise DomainError("ACCOUNT_EXISTS", "该手机号已注册，请登录；尚未设置密码可通过「设置／找回密码」完成。", 409)
            id = str(uuid4())
            cx.execute("INSERT INTO accounts (id,env,phone,role,actor,created_at,password_hash) VALUES (?,?,?,?,?,?,?)",
                       (id, self.settings.env, data.phone, data.role, data.role + ":" + id, time.time(), encoded))
            account = self.account(cx, data.phone)
            self.ensure_workspaces(cx, account)
            user, token, csrf = self.issue(cx, account, request, data.role)
        return self.result(user, token, csrf, response)

    def login_password(self, data, request, response, admin_only=False):
        self.origin(request)
        ip = request.client.host if request.client else "unknown"
        self.limit("password-ip:" + ip, 40, 600)
        self.limit("password-phone:" + data.phone, 10, 600)
        with self.tx() as cx:
            account = self.account(cx, data.phone)
        encoded = account["password_hash"] if account else None
        if not verify_password(data.password, encoded):
            raise DomainError("PASSWORD_INVALID", "手机号或密码不正确；未设置密码可使用「设置／找回密码」。", 400)
        with self.tx() as cx:
            fresh = self.account(cx, data.phone)
            # A concurrent reset must not issue a session for the previous password.
            if not fresh or fresh["password_hash"] != encoded:
                raise DomainError("PASSWORD_INVALID", "密码已更新，请使用新密码登录。", 400)
            if admin_only and fresh["role"] != "admin":
                raise DomainError("ADMIN_REQUIRED", "此账号没有平台管理权限，请使用工作人员账号。", 403)
            user, token, csrf = self.issue(cx, fresh, request, "enterprise" if admin_only else data.role, 'admin' if admin_only else 'user')
        return self.result(user, token, csrf, response)

    def reset_password(self, data, request, response):
        self.verify_code(data, request, "reset")
        encoded = hash_password(data.password)
        with self.tx() as cx:
            account = self.account(cx, data.phone)
            if not account:
                raise DomainError("ACCOUNT_NOT_REGISTERED", "该手机号尚未注册，请先完成验证码注册。", 400)
            scope=self.request_scope(request)
            if scope == 'admin' and account['role'] != 'admin':
                raise DomainError('ADMIN_REQUIRED', '此账号没有平台管理权限。',403)
            previous = cx.execute("SELECT workspace_role FROM sessions WHERE token_hash=? AND account_id=? AND session_scope=? AND expires_at>?", (digest(request.cookies.get(self.cookie_name(scope, self.request_tab(request)), "")), account["id"], scope, time.time())).fetchone()
            cx.execute("UPDATE accounts SET password_hash=? WHERE id=?", (encoded, account["id"]))
            cx.execute("DELETE FROM sessions WHERE account_id=?", (account["id"],))
            account = self.account(cx, data.phone)
            user, token, csrf = self.issue(cx, account, request, 'enterprise' if scope == 'admin' else previous["workspace_role"] if previous else None, scope)
        return self.result(user, token, csrf, response)

    def switch_workspace(self, data, request, response):
        # Recheck inside the write transaction, so concurrent switches cannot reuse a rotated cookie.
        with self.tx() as cx:
            current = self.session_row(cx, request)
            self.check_csrf(current, request)
            if current['session_scope'] == 'admin':
                raise DomainError('ADMIN_WORKSPACE_FIXED','管理端不能切换用户工作空间，请另开用户端页面。',403)
            account = cx.execute("SELECT * FROM accounts WHERE id=?", (current["id"],)).fetchone()
            self.workspace(cx, account, data.role)  # Switching cannot silently fall back or bypass qualification.
            target_tab = self.request_tab(request, "x-new-session-tab")
            if target_tab is not None and self.request_tab(request) is None:
                raise DomainError("SESSION_TAB_INVALID", "切换工作空间需要有效的页面会话。", 400)
            user, token, csrf = self.issue(cx, account, request, data.role, target_tab=target_tab)
        return self.result(user, token, csrf, response)

    def session_row(self, cx, request):
        scope=self.request_scope(request)
        row = cx.execute("SELECT a.*,s.csrf,s.expires_at,s.workspace_role,s.session_scope FROM sessions s JOIN accounts a ON a.id=s.account_id WHERE s.token_hash=? AND s.session_scope=? AND a.env=? AND s.expires_at>?", (digest(request.cookies.get(self.cookie_name(scope, self.request_tab(request)), "")), scope, self.settings.env, time.time())).fetchone()
        if not row:
            raise DomainError("AUTH_REQUIRED", "请登录后继续。", 401)
        if row["disabled"]:
            raise DomainError("ACCOUNT_DISABLED", "账号已被平台暂停使用，请联系平台工作人员。", 403)
        return {**self.workspace(cx, row, row["workspace_role"],scope), "csrf": row["csrf"], "expires_at": row["expires_at"]}

    def check_csrf(self, row, request):
        self.origin(request)
        if not hmac.compare_digest(row["csrf"], request.headers.get("x-csrf-token", "")):
            raise DomainError("CSRF_INVALID", "登录状态校验失败，请刷新页面后重试。", 403)

    def session(self, request, unsafe=True):
        with self.tx() as cx:
            row = self.session_row(cx, request)
        if unsafe and request.method not in {"GET", "HEAD", "OPTIONS"}:
            self.check_csrf(row, request)
        return row

    def actor(self, request: Request):
        return self.session(request)["actor"]

    def enterprise_owner_verified(self, actor):
        with self.tx() as cx:
            row = cx.execute("""SELECT a.* FROM account_workspaces w JOIN accounts a ON a.id=w.account_id
                WHERE w.actor=? AND w.role='enterprise' AND a.env=?""", (actor, self.settings.env)).fetchone()
            return bool(row and not row["disabled"] and (row["role"] == "admin" or EnterpriseVerification.status(cx, row["id"]) == "approved"))

    def enterprise_company_name(self, actor):
        with self.tx() as cx:
            row = cx.execute('SELECT a.id FROM account_workspaces w JOIN accounts a ON a.id=w.account_id WHERE w.actor=? AND w.role=? AND a.env=?',
                (actor, 'enterprise', self.settings.env)).fetchone()
            qualification = self.verification.latest(cx, row['id']) if row else None
            return qualification['company_name'] if qualification and qualification['status'] == 'approved' else ''

    def actor_active(self, actor):
        with self.tx() as cx:
            return bool(cx.execute('SELECT 1 FROM accounts a JOIN account_workspaces w ON w.account_id=a.id WHERE a.env=? AND w.actor=? AND a.disabled=0 AND a.role!=?',
                (self.settings.env, actor, 'admin')).fetchone())

    def admin(self, request: Request):
        row = self.session(request)
        if self.request_scope(request) != 'admin':
            raise DomainError('ADMIN_REQUIRED','请从管理端发起此操作。',403)
        if row["session_scope"] != 'admin' or row["account_role"] != "admin" or row["workspace_role"] != "enterprise":
            raise DomainError("ADMIN_REQUIRED", "此操作仅供管理员使用。", 403)
        return row["actor"]

    def logout(self, request, response):
        self.session(request)
        scope=self.request_scope(request)
        with self.tx() as cx:
            cx.execute("DELETE FROM sessions WHERE token_hash=? AND session_scope=?", (digest(request.cookies.get(self.cookie_name(scope, self.request_tab(request)), "")),scope))
        response.delete_cookie(self.cookie_name(scope, self.request_tab(request)), path="/", secure=self.settings.session_cookie_secure, httponly=True, samesite="strict")
        return {"message": "已退出登录"}
