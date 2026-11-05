"""Private company evidence and explicit human review; never automatic approval."""
import re
import time
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .errors import DomainError


class EnterpriseReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject", "revoke"]
    reason: str = Field(min_length=5, max_length=1000)


class EnterpriseVerification:
    @staticmethod
    def setup(cx):
        cx.executescript("""
            CREATE TABLE IF NOT EXISTS enterprise_submissions (
                id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
                company_name TEXT NOT NULL, credit_code TEXT NOT NULL,
                legal_representative TEXT NOT NULL, contact_name TEXT NOT NULL,
                license_name TEXT NOT NULL, authorization_name TEXT NOT NULL,
                license_file TEXT NOT NULL, authorization_file TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','revoked')),
                reason TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL,
                reviewed_at REAL, reviewed_by TEXT);
            CREATE INDEX IF NOT EXISTS idx_enterprise_account ON enterprise_submissions(account_id,created_at);
            CREATE TABLE IF NOT EXISTS enterprise_review_events (
                id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES enterprise_submissions(id),
                reviewer_id TEXT NOT NULL REFERENCES accounts(id), decision TEXT NOT NULL,
                reason TEXT NOT NULL, created_at REAL NOT NULL);
        """)

    def __init__(self, auth):
        self.auth = auth
        self.folder = auth.settings.data_dir / "enterprise_credentials"

    @staticmethod
    def latest(cx, account_id):
        return cx.execute("SELECT * FROM enterprise_submissions WHERE account_id=? ORDER BY created_at DESC,id DESC LIMIT 1", (account_id,)).fetchone()

    @classmethod
    def status(cls, cx, account_id):
        row = cls.latest(cx, account_id)
        return row["status"] if row else "unsubmitted"

    @staticmethod
    def public(row):
        if not row:
            return None
        # Never expose disk paths or other accounts' credentials.
        return {key: row[key] for key in ("id", "company_name", "credit_code", "legal_representative", "contact_name", "license_name", "authorization_name", "status", "reason", "created_at", "reviewed_at")}

    def mine(self, user):
        with self.auth.tx() as cx:
            row = self.latest(cx, user["id"])
        return {"status": row["status"] if row else "unsubmitted", "submission": self.public(row)}

    @staticmethod
    def file_type(content, filename):
        if not content or len(content) > 5 * 1024 * 1024:
            raise DomainError("CREDENTIAL_FILE_SIZE", "每份资质文件需大于 0 字节且不超过 5MB。", 422)
        name = re.split(r"[/\\]", filename or "材料")[-1][:100]
        suffix = Path(name).suffix.lower()
        valid = ((suffix == ".pdf" and content.startswith(b"%PDF-")) or
                 (suffix == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n")) or
                 (suffix in {".jpg", ".jpeg"} and content.startswith(b"\xff\xd8\xff")))
        if not valid:
            raise DomainError("CREDENTIAL_FILE_TYPE", "资质材料仅支持 PDF、PNG、JPG，文件内容需与类型一致。", 422)
        return name, suffix

    def submit(self, user, fields, license, authorization):
        fields = {key: value.strip() for key, value in fields.items()}
        for key, label in (("company_name", "企业全称"), ("legal_representative", "法定代表人"), ("contact_name", "招聘联系人")):
            if not 2 <= len(fields[key]) <= 100:
                raise DomainError("CREDENTIAL_FIELD", label + "需填写 2–100 个字符。", 422)
        # Format validation is not a registry lookup or a conclusion about authenticity.
        if not re.fullmatch(r"[0-9A-HJ-NPQRTUWXY]{18}", fields["credit_code"]):
            raise DomainError("CREDIT_CODE_FORMAT", "请填写营业执照上的 18 位统一社会信用代码。", 422)
        license_name, license_suffix = self.file_type(*license)
        authorization_name, authorization_suffix = self.file_type(*authorization)
        id = str(uuid4())
        folder = (self.folder / id).resolve()
        if folder.parent != self.folder.resolve():
            raise DomainError("CREDENTIAL_STORAGE", "资质文件保存失败。", 500)
        paths = [folder / ("license" + license_suffix), folder / ("authorization" + authorization_suffix)]
        created = False
        try:
            with self.auth.tx() as cx:
                status = self.status(cx, user["id"])
                if status in {"pending", "approved"}:
                    raise DomainError("VERIFICATION_LOCKED", "资质正在审核或已通过，请勿重复提交。", 409)
                folder.mkdir(parents=True, exist_ok=False)
                created = True
                paths[0].write_bytes(license[0]); paths[1].write_bytes(authorization[0])
                cx.execute("""INSERT INTO enterprise_submissions (id,account_id,company_name,credit_code,
                    legal_representative,contact_name,license_name,authorization_name,license_file,
                    authorization_file,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (id, user["id"], fields["company_name"], fields["credit_code"], fields["legal_representative"],
                     fields["contact_name"], license_name, authorization_name, paths[0].name, paths[1].name, "pending", time.time()))
        except Exception:
            # Only this submission's two known files, never a recursive directory operation.
            if created:
                for path in paths:
                    path.unlink(missing_ok=True)
                folder.rmdir()
            raise
        return self.mine(user)

    def list(self, user):
        with self.auth.tx() as cx:
            rows = cx.execute("""SELECT s.* FROM enterprise_submissions s JOIN accounts a ON a.id=s.account_id
                WHERE a.env=? AND s.id=(SELECT id FROM enterprise_submissions WHERE account_id=s.account_id ORDER BY created_at DESC,id DESC LIMIT 1)
                ORDER BY s.created_at DESC""", (self.auth.settings.env,)).fetchall()
        return [self.public(row) for row in rows]

    def review(self, id, data, user):
        reason = data.reason.strip()
        if len(reason) < 5:
            raise DomainError("REVIEW_REASON", "请填写至少 5 个字符的核验依据或退回原因。", 422)
        with self.auth.tx() as cx:
            row = cx.execute("""SELECT s.* FROM enterprise_submissions s JOIN accounts a ON a.id=s.account_id
                WHERE s.id=? AND a.env=?""", (id, self.auth.settings.env)).fetchone()
            if not row:
                raise DomainError("NOT_FOUND", "资质申请不存在。", 404)
            latest = self.latest(cx, row["account_id"])
            if latest["id"] != id or (data.decision == "revoke" and row["status"] != "approved") or (data.decision != "revoke" and row["status"] != "pending"):
                raise DomainError("VERIFICATION_CONFLICT", "申请状态已变化，请刷新后重试。", 409)
            status = {"approve": "approved", "reject": "rejected", "revoke": "revoked"}[data.decision]
            stamp = time.time()
            cx.execute("UPDATE enterprise_submissions SET status=?,reason=?,reviewed_at=?,reviewed_by=? WHERE id=?", (status, reason, stamp, user["id"], id))
            cx.execute("INSERT INTO enterprise_review_events VALUES (?,?,?,?,?,?)", (str(uuid4()), id, user["id"], data.decision, reason, stamp))
            if status != "approved":
                cx.execute("DELETE FROM sessions WHERE account_id=? AND workspace_role='enterprise'", (row["account_id"],))
            result = self.public(cx.execute("SELECT * FROM enterprise_submissions WHERE id=?", (id,)).fetchone())
        return result

    def evidence(self, id, kind, user):
        with self.auth.tx() as cx:
            row = cx.execute("""SELECT s.* FROM enterprise_submissions s JOIN accounts a ON a.id=s.account_id
                WHERE s.id=? AND a.env=?""", (id, self.auth.settings.env)).fetchone()
        admin = user.get("session_scope") == "admin" and user["account_role"] == "admin" and user["workspace_role"] == "enterprise"
        if not row or (row["account_id"] != user["id"] and not admin) or kind not in {"license", "authorization"}:
            raise DomainError("NOT_FOUND", "资质材料不存在或无权查看。", 404)
        path = (self.folder / id / row[kind + "_file"]).resolve()
        if not path.is_relative_to(self.folder.resolve()) or not path.is_file():
            raise DomainError("NOT_FOUND", "资质材料不存在。", 404)
        return path, row[kind + "_name"]
