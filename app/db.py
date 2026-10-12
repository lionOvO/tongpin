import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

TABLES = {
    "job_profiles": {}, "candidates": {},
    "resumes": {"candidate_id": "candidates"},
    "batches": {"job_id": "job_profiles", "resume_id": "resumes"},
    "ability_reports": {"job_id": "job_profiles", "resume_id": "resumes"},
    "review_events": {"report_id": "ability_reports"},
    "calibration_memory": {"job_id": "job_profiles", "source_event_id": "review_events"},
    "audit_logs": {},
    "fit_reports": {"resume_id": "resumes", "job_id": "job_profiles"},
    "role_benchmarks": {"job_id": "job_profiles"},
    "hiring_briefs": {"job_id": "job_profiles"},
    "jd_diagnoses": {"job_id": "job_profiles"},
    "preference_submissions": {"job_id": "job_profiles", "resume_id": "resumes"},
    "match_results": {"job_id": "job_profiles", "resume_id": "resumes", "ent_submission_id": "preference_submissions", "cand_submission_id": "preference_submissions"},
    "job_comparison_runs": {"resume_id": "resumes"},
}


def now():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, settings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = settings.data_dir / "talent.sqlite3"
        self.lock = threading.RLock()
        with self.transaction() as cx:
            cx.execute("PRAGMA journal_mode=WAL")
            for table, refs in TABLES.items():
                extra = "".join(f', {key} TEXT REFERENCES {target}(id)' for key, target in refs.items())
                cx.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, owner TEXT NOT NULL, env TEXT NOT NULL CHECK(env IN ('dev','demo','prod')), data_origin TEXT NOT NULL CHECK(data_origin IN ('synthetic','real')), created_at TEXT NOT NULL, payload TEXT NOT NULL{extra})")
                cx.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_scope ON {table}(env, owner)")
                for key in refs:
                    cx.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_{key} ON {table}({key})")

    @contextmanager
    def transaction(self):
        with self.lock:
            cx = sqlite3.connect(self.path, timeout=30)
            cx.row_factory = sqlite3.Row
            cx.execute("PRAGMA foreign_keys=ON")
            try:
                yield cx
                cx.commit()
            except Exception:
                cx.rollback()
                raise
            finally:
                cx.close()

    def decode(self, row):
        if row is None:
            return None
        obj = json.loads(row["payload"])
        obj.update({k: row[k] for k in row.keys() if k != "payload"})
        return obj

    def insert(self, table, payload, owner, origin="synthetic", cx=None, **refs):
        assert table in TABLES and set(refs) <= set(TABLES[table])
        obj = {"id": str(uuid4()), "owner": owner, "env": self.settings.env, "data_origin": origin, "created_at": now()}
        keys = [*obj, "payload", *refs]
        values = [*obj.values(), json.dumps(payload, ensure_ascii=False), *refs.values()]
        sql = f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})"
        if cx is not None:
            cx.execute(sql, values)
        else:
            with self.transaction() as tx:
                tx.execute(sql, values)
        return {**payload, **obj, **refs}

    def get(self, table, id, cx=None):
        assert table in TABLES
        sql = f"SELECT * FROM {table} WHERE id=? AND env=?"
        if cx is not None:
            return self.decode(cx.execute(sql, (id, self.settings.env)).fetchone())
        with self.transaction() as tx:
            return self.decode(tx.execute(sql, (id, self.settings.env)).fetchone())

    def list(self, table, owner=None, **refs):
        assert table in TABLES and set(refs) <= set(TABLES[table])
        filters = {"env": self.settings.env, **refs}
        if owner is not None:
            filters["owner"] = owner
        with self.transaction() as cx:
            rows = cx.execute(f"SELECT * FROM {table} WHERE " + " AND ".join(f"{k}=?" for k in filters) + " ORDER BY created_at DESC, id", list(filters.values())).fetchall()
            return [self.decode(row) for row in rows]

    def update(self, table, id, patch, cx=None):
        if cx is None:
            with self.transaction() as tx:
                return self.update(table, id, patch, tx)
        obj = self.get(table, id, cx)
        if not obj:
            raise KeyError(id)
        payload = {k: v for k, v in obj.items() if k not in {"id", "owner", "env", "data_origin", "created_at", *TABLES[table]}}
        payload.update(patch)
        cx.execute(f"UPDATE {table} SET payload=? WHERE id=? AND env=?", (json.dumps(payload, ensure_ascii=False), id, self.settings.env))
        return {**obj, **patch}

    def audit(self, event, detail, owner="enterprise:demo", result="正常", cx=None):
        return self.insert("audit_logs", {"event_type": event, "detail": detail, "result": result}, owner, cx=cx)

