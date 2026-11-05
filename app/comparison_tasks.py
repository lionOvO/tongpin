"""Durable, idempotent candidate job comparisons using direct DeepSeek analysis."""
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pydantic import BaseModel, Field, ConfigDict
from .models import CompareInput
from .db import now
from .errors import DomainError
from .job_fit import content_hash, targets_for, evaluate_target, rank_results, present_comparison, FIT_POLICY


class ComparisonTaskInput(CompareInput):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=8, max_length=100)


class ComparisonRetryInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=8, max_length=100)


class ComparisonTasks:
    def __init__(self, svc, auth):
        self.svc, self.db, self.auth = svc, svc.db, auth
        self.pool = None
        self.slots = threading.BoundedSemaphore(8)

    def start(self):
        if self.pool is not None: return
        for row in self.db.list('job_comparison_runs'):
            if row.get('status') in {'queued', 'running'}:
                self.db.update('job_comparison_runs', row['id'], dict(status='interrupted', finished_at=now(), message='服务已重启，已完成结果保留；请核对后重新分析未完成岗位。'))
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='job-fit')

    def get(self, id, actor):
        self.svc.candidate(actor)
        row = self.db.get('job_comparison_runs', id)
        if not row or row['owner'] != actor: raise DomainError('NOT_FOUND', '岗位契合度记录不存在或无权访问。', 404)
        # Inputs and fingerprints are private worker state; do not serialize them.
        return present_comparison({k: v for k, v in row.items() if k not in {'targets', 'resume_snapshot', 'fingerprint', 'owner'}})

    def list(self, actor):
        self.svc.candidate(actor)
        return [self.get(r['id'], actor) for r in self.db.list('job_comparison_runs', owner=actor)[:50]]

    def retry(self, id, data, actor):
        self.get(id, actor)  # Check ownership before reading private worker state.
        previous = self.db.get('job_comparison_runs', id)
        if previous.get('status') not in {'partial', 'failed', 'interrupted'} or not previous.get('targets'):
            raise DomainError('COMPARISON_NOT_RETRYABLE', '此记录没有需要重试的岗位。', 409)
        inputs = dict(resume_id=previous['resume_id'], request_id=data.request_id)
        if previous.get('job_ids'): inputs['job_ids'] = previous['job_ids']
        else: inputs['job_texts'] = [t['text'] for t in previous['targets']]
        return self.submit(ComparisonTaskInput(**inputs), actor, previous=previous)

    def submit(self, data, actor, *, previous=None):
        self.svc.writable(); self.svc.candidate(actor)
        if self.pool is None: raise DomainError('COMPARISON_BUSY', '分析服务尚未就绪，请稍后重试。', 503)
        resume = self.svc.active_resume(data.resume_id, actor)
        targets = targets_for(self.svc, data, actor)
        fingerprint = content_hash([resume['text'], targets])
        if previous and previous.get('fingerprint') != fingerprint:
            raise DomainError('COMPARISON_INPUT_CHANGED', '简历或岗位已变化，请重新完整分析，避免合并不同版本的结果。', 409)
        completed = rank_results(previous.get('ranked_results', [])) if previous else []
        with self.db.transaction() as cx:
            cx.execute('BEGIN IMMEDIATE')
            for row in self.db.list('job_comparison_runs', owner=actor):
                if row.get('request_id') == data.request_id:
                    if row['resume_id'] != data.resume_id or row.get('fingerprint') != fingerprint:
                        raise DomainError('TASK_REQUEST_CONFLICT', '资料或所选岗位已变化，请重新提交。', 409)
                    if row.get('retry_of') != (previous['id'] if previous else None):
                        raise DomainError('TASK_REQUEST_CONFLICT', '请求编号已用于其他分析，请刷新后重试。', 409)
                    return self.get(row['id'], actor)
                if row['resume_id'] == data.resume_id and row.get('status') in {'queued', 'running'}:
                    if row.get('fingerprint') == fingerprint: return self.get(row['id'], actor)
                    raise DomainError('COMPARISON_RUNNING', '这份简历已有分析任务，请先等待完成。', 409)
            if not self.slots.acquire(blocking=False): raise DomainError('COMPARISON_BUSY', '分析任务较多，请稍后重试。', 429)
            try:
                row = self.db.insert('job_comparison_runs', dict(status='queued', processed=len(completed), total=len(targets),
                    request_id=data.request_id, fingerprint=fingerprint, targets=targets, resume_snapshot=resume,
                    mode=self.svc.settings.llm_mode, resume_name=resume['display_name'], ranked_results=completed, errors=[], job_ids=data.job_ids,
                    retry_of=previous['id'] if previous else None,
                    message='等待分析', model=self.svc.models.resolve('deepseek').public(self.svc.models.enabled),
                    policy_version=FIT_POLICY, rubric_version=self.svc.config.get('rubric')['version']), actor, resume['data_origin'], cx=cx, resume_id=resume['id'])
            except Exception:
                self.slots.release(); raise
        try:
            context = copy_context()
            future = self.pool.submit(context.run, self.run, row['id'], actor)
        except RuntimeError:
            self.slots.release()
            self.db.update('job_comparison_runs', row['id'], dict(status='interrupted', message='服务正在重启，请稍后重试。', finished_at=now()))
            raise DomainError('COMPARISON_BUSY', '服务正在重启，请稍后重试。', 503) from None
        future.add_done_callback(lambda _: self.slots.release())
        return self.get(row['id'], actor)

    def run(self, id, actor):
        row = self.db.get('job_comparison_runs', id)
        results, errors = list(row.get('ranked_results', [])), []
        completed_refs = {r['job_ref'] for r in results}
        processed = len(results)
        try:
            self.db.update('job_comparison_runs', id, dict(status='running', started_at=now(), message='正在分析岗位'))
            for target in row['targets']:
                if target['job_ref'] in completed_refs: continue
                try:
                    if not self.auth.actor_active(actor): raise DomainError('ACCOUNT_DISABLED', '账号状态已变化，分析停止。', 403)
                    resume = self.svc.active_resume(row['resume_id'], actor)
                    if content_hash(resume['text']) != content_hash(row['resume_snapshot']['text']):
                        raise DomainError('RESUME_CHANGED', '简历已修改，请使用最新简历重新分析。', 409)
                    result = evaluate_target(self.svc, target, resume, actor)
                    if not self.auth.actor_active(actor): raise DomainError('ACCOUNT_DISABLED', '账号状态已变化，分析停止。', 403)
                    results.append(result)
                except DomainError as error:
                    errors.append(dict(job_ref=target['job_ref'], job_id=target.get('job_id'), code=error.code, error=error.message))
                    if error.code in {'COST_BUDGET', 'ACCOUNT_DISABLED', 'RESUME_CHANGED', 'NOT_FOUND'}: break
                processed += 1
                self.db.update('job_comparison_runs', id, dict(processed=processed, ranked_results=rank_results(results), errors=errors))
            status = 'completed' if not errors else 'partial' if results else 'failed'
            message = f'已完成 {len(results)} 个岗位的契合分析。' if results else '未生成新结果，请查看失败原因。'
        except Exception:
            status, message = ('partial' if results else 'failed'), '分析服务暂时异常，已完成结果保留，请稍后重试。'
            errors.append(dict(code='COMPARISON_FAILED', error=message))
        self.db.update('job_comparison_runs', id, dict(status=status, message=message, processed=processed,
            ranked_results=rank_results(results), errors=errors, finished_at=now()))

    def close(self):
        if self.pool:
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.pool = None
