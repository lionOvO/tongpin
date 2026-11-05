"""Candidate Agent adapters for existing job visibility and comparison services."""
import re
import hashlib
from .errors import DomainError
from .security import redact
from .job_fit import content_hash, rank_results
from .comparison_tasks import ComparisonTaskInput


class WorkspaceJobs:
    def __init__(self, workspace, tasks):
        self.ws = workspace; self.svc = workspace.svc; self.db = workspace.db; self.tasks = tasks

    def available(self, entry, actor):
        job = self.db.get('job_profiles', entry['job_id'])
        if not job or job['status'] != '已确认' or not self.svc.job_visible(job, actor): return None
        if content_hash([job['version'], job['source_jd'], job['profile']]) != entry['fingerprint']: return None
        return job

    def public(self, row, actor):
        jobs = []
        entries = row.get('agent_jobs', [])
        for entry in entries:
            job = self.available(entry, actor)
            if job:
                jobs.append({'ref': entry['ref'], 'id': job['id'], 'title': job['title'],
                    'company': self.svc.enterprise_company_name(job['owner']) if job['owner'].startswith('enterprise:') else '个人岗位参照'})
        comparison = None
        if row.get('agent_comparison_id'):
            try:
                comparison = self.tasks.get(row['agent_comparison_id'], actor)
                if comparison.get('resume_id') != row['resume_id']:
                    return {'jobs': jobs, 'comparison': None}
                # Saved comparisons are snapshots; recheck visibility and version before showing in Agent.
                saved = self.db.get('job_comparison_runs', row['agent_comparison_id'])
                permitted = set()
                for target in saved.get('targets', []):
                    job = self.db.get('job_profiles', target.get('job_id', ''))
                    if job and job['status'] == '已确认' and self.svc.job_visible(job, actor) and content_hash([job['profile'], job['source_jd'], job['version']]) == target['fingerprint']:
                        permitted.add(job['id'])
                results = comparison.get('ranked_results', [])
                comparison['ranked_results'] = rank_results([r for r in results if r.get('job_id') in permitted])
                comparison['unavailable_count'] = len(results) - len(comparison['ranked_results'])
                comparison.pop('job_ids', None)
                comparison['errors'] = [{'error': item['error']} for item in comparison.get('errors', [])]
                comparison['notice'] = '基于发起时已保存的简历；未融入简历的本人补充不参与本次分析。缺少证据仅作提示，不扣档。'
            except DomainError:
                comparison = None
        return {'jobs': jobs, 'comparison': comparison}

    def tools(self, id, actor, token, guard):
        def execute(name, args):
            guard()
            row = self.ws.owned(id, actor)
            if name == 'search_jobs':
                words = [w for w in re.split(r'[\s,，、]+', args.query.casefold()) if w]
                found = []
                for job in self.db.list('job_profiles'):
                    if job['status'] != '已确认' or not self.svc.job_visible(job, actor): continue
                    if words and not any(w in (job['title'] + ' ' + job['source_jd']).casefold() for w in words): continue
                    found.append({'ref': 'P' + hashlib.sha256(job['id'].encode()).hexdigest()[:12], 'job_id': job['id'],
                        'fingerprint': content_hash([job['version'], job['source_jd'], job['profile']])})
                    if len(found) >= 12: break
                # One visible search scope per task, bounded to twelve jobs. Repeated search replaces it.
                with self.db.transaction() as cx:
                    cx.execute('BEGIN IMMEDIATE')
                    fresh = self.ws.owned(id, actor, cx)
                    if fresh.get('running') != token: raise DomainError('AI_CANCELLED', '本次协作已停止。', 409)
                    self.db.update('ai_sessions', id, {'agent_jobs': found}, cx)
                result = []
                for entry in found:
                    job = self.available(entry, actor)
                    if job: result.append({'ref': entry['ref'], 'title': redact(job['title']),
                        'summary': redact(job['source_jd'])[:1200]})
                return {'jobs': result, 'limit': 12, 'notice': '仅查询平台可见岗位，文字命中不代表契合度；请调用后台分析工具。'}
            if name == 'start_comparison':
                if row.get('agent_comparison_run') == token and row.get('agent_comparison_id'):
                    return self.summary(self.public(row, actor)['comparison'])
                refs = list(dict.fromkeys(args.job_refs)); lookup = {j['ref']: j for j in row.get('agent_jobs', [])}
                if any(ref not in lookup or not self.available(lookup[ref], actor) for ref in refs):
                    raise DomainError('AI_JOB_SCOPE', '只能分析本任务查询过且当前仍可见的岗位，请重新查询。', 409)
                guard()
                result = self.tasks.submit(ComparisonTaskInput(resume_id=row['resume_id'], job_ids=[lookup[ref]['job_id'] for ref in refs],
                    request_id='agent-' + id + '-' + token), actor)
                # Record the durable task even if a cancellation races its dispatch; never orphan it.
                with self.db.transaction() as cx:
                    cx.execute('BEGIN IMMEDIATE')
                    fresh = self.ws.owned(id, actor, cx)
                    if fresh.get('running') == token or (fresh.get('agent_run') or {}).get('id') == token:
                        self.db.update('ai_sessions', id, {'agent_comparison_id': result['id'], 'agent_comparison_run': token}, cx)
                guard()
                return self.summary(self.public(self.ws.owned(id, actor), actor)['comparison'])
            return self.summary(self.public(row, actor)['comparison'])
        return execute

    @staticmethod
    def summary(result):
        if not result: return {'status': 'none', 'notice': '本工作区还没有关联的岗位分析。'}
        return {key: result.get(key) for key in ('status', 'processed', 'total', 'message', 'notice')} | {
            'results': [{'title': r['job_title'], 'rank': r.get('rank'), 'fit': r['fit_summary']}
                        for r in result.get('ranked_results', [])],
            'notice': result.get('notice', '') + ' 详细结果已显示在工作区岗位卡片中；不要自行改写档位或排名。'}
