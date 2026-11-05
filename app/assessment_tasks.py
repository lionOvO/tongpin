"""Durable report progress; short HTTP requests never own a model generation."""
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pydantic import BaseModel, Field, ConfigDict
from .db import now
from .errors import DomainError
from .models import AssessmentInput


class ReportTaskInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    job_id: str
    resume_ids: list[str] = Field(min_length=1, max_length=50)
    request_id: str = Field(min_length=8, max_length=100)


class AssessmentTasks:
    def __init__(self, svc, auth):
        self.svc, self.db, self.auth = svc, svc.db, auth
        self.pool = None
        self.slots = threading.BoundedSemaphore(8)

    def start(self):
        if self.pool is None:
            self.recover()
            self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='ability-report')

    def recover(self):
        # A restart cannot safely replay a paid model call.
        for row in self.db.list('assessment_tasks'):
            if row['status'] in {'queued', 'running'}:
                self.db.update('assessment_tasks', row['id'], {'status': 'interrupted', 'finished_at': now(),
                    'message': '服务已重启，任务已中断。已生成的报告保留，请核对后重试。'})

    def access(self, row, actor):
        if not row or row['owner'] != actor:
            raise DomainError('NOT_FOUND', '报告任务不存在或无权访问。', 404)
        self.svc.owned('job_profiles', row['job_id'], actor)
        for id in row['resume_ids']:
            resume = self.db.get('resumes', id)
            if not resume or resume['owner'] != actor or not self.svc.material_visible(resume):
                raise DomainError('RESUME_CONSENT_UNAVAILABLE', '简历授权已结束，无法查看此任务。', 403)
        return row

    def get(self, id, actor):
        return self.access(self.db.get('assessment_tasks', id), actor)

    def list(self, job_id, actor):
        self.svc.owned('job_profiles', job_id, actor)
        rows = []
        for row in self.db.list('assessment_tasks', actor, job_id=job_id):
            try: rows.append(self.access(row, actor))
            except DomainError: continue
            if len(rows) == 20: break
        return sorted(rows, key=lambda row: row['status'] not in {'queued', 'running'})

    def submit(self, data, actor):
        self.svc.writable()
        pool = self.pool
        if pool is None:
            raise DomainError('ASSESSMENT_BUSY', '报告服务尚未就绪，请稍后重试。', 503)
        ids = list(dict.fromkeys(data.resume_ids))
        with self.db.transaction() as cx:
            cx.execute('BEGIN IMMEDIATE')
            job = self.svc.owned('job_profiles', data.job_id, actor)
            if job['status'] != '已确认':
                raise DomainError('PROFILE_UNCONFIRMED', '请先确认岗位画像。', 409)
            for id in ids:
                self.svc.resume_job_scope(self.svc.active_resume(id, actor), data.job_id)
            for row in self.db.list('assessment_tasks', actor, job_id=data.job_id):
                if row['request_id'] == data.request_id:
                    if row['resume_ids'] != ids:
                        raise DomainError('TASK_REQUEST_CONFLICT', '请求内容已变化，请刷新。', 409)
                    return self.access(row, actor)
                if row['status'] in {'queued', 'running'} and set(ids) & set(row['resume_ids']):
                    if row['resume_ids'] == ids: return self.access(row, actor)
                    raise DomainError('ASSESSMENT_RUNNING', '所选简历已有报告任务，请等待完成。', 409)
            if not self.slots.acquire(blocking=False):
                raise DomainError('ASSESSMENT_BUSY', '报告任务较多，请稍后重试。', 429)
            try:
                row = self.db.insert('assessment_tasks', {'resume_ids': ids, 'request_id': data.request_id,
                    'status': 'queued', 'processed': 0, 'report_ids': [], 'errors': [], 'message': '等待分析',
                    'model': self.svc.models.resolve('deepseek').public(self.svc.models.enabled), 'finished_at': None}, actor, job['data_origin'],
                    cx=cx, job_id=data.job_id)
            except Exception:
                self.slots.release()
                raise
        context = copy_context()
        try: future = pool.submit(context.run, self.run, row['id'], actor)
        except RuntimeError:
            self.slots.release()
            self.db.update('assessment_tasks', row['id'], {'status': 'interrupted', 'finished_at': now(), 'message': '服务正在重启，请稍后重试。'})
            raise DomainError('ASSESSMENT_BUSY', '服务正在重启，请稍后重试。', 503) from None
        future.add_done_callback(lambda _: self.slots.release())
        return row

    def run(self, id, actor):
        row = self.db.get('assessment_tasks', id)
        reports, errors, processed = [], [], 0
        try:
            self.db.update('assessment_tasks', id, {'status': 'running', 'message': '正在分析', 'started_at': now()})
            for resume_id in row['resume_ids']:
                if not self.svc.enterprise_hiring_enabled(actor):
                    raise DomainError('ENTERPRISE_VERIFICATION_REQUIRED', '招聘权限已暂停，任务已停止。', 403)
                result = self.svc.assess(AssessmentInput(job_id=row['job_id'], resume_ids=[resume_id]), actor,
                    authorize=lambda: self.svc.enterprise_hiring_enabled(actor))
                reports.extend(r['id'] for r in result['reports'])
                errors.extend(result['errors']); processed += 1
                self.db.update('assessment_tasks', id, {'processed': processed, 'report_ids': reports, 'errors': errors})
                if any(e['code'] in {'COST_BUDGET', 'ASSESSMENT_PAUSED'} for e in errors): break
            status = 'completed' if not errors else 'partial' if reports else 'failed'
            message = f'已生成 {len(reports)} 份报告。' if reports else '未生成新报告，请查看失败原因。'
        except DomainError as error:
            status, message = 'partial' if reports else 'failed', error.message
            errors.append({'code': error.code, 'message': error.message})
        except Exception:
            status, message = 'partial' if reports else 'failed', '报告服务发生异常，请稍后重试。'
            errors.append({'code': 'ASSESSMENT_FAILED', 'message': message})
        self.db.update('assessment_tasks', id, {'status': status, 'processed': processed,
            'report_ids': reports, 'errors': errors, 'message': message, 'finished_at': now()})

    def close(self):
        if self.pool:
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.pool = None
