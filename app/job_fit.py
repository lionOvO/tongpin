"""Candidate-facing fit bands derived from cited project and technical evidence."""
import hashlib
import json
from .errors import DomainError
from .security import redact

FIT_POLICY = 'job-fit-known-evidence-v2'
FIT_BASIS = '只按已有主要技能与项目证据归纳五档，缺失项不计入判定；同档位并列，完全没有可判断依据时仅提示、不排位。'
FIT_BANDS = {1: ('very_low', '很低契合'), 2: ('low', '较低契合'), 3: ('medium', '一般契合'),
             4: ('high', '较高契合'), 5: ('very_high', '很高契合')}


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def fit_summary(dimensions, skills):
    by_id = {d['dimension_id']: d for d in dimensions}
    def level(row):
        if not row or not row.get('evidence') or row.get('tier') == 'insufficient':
            return None
        # Old D4 ranges model possible values of unknown skills. They cannot be
        # used as facts; use the actual known skill rows instead of this aggregate.
        if row.get('dimension_id') == 'D4' and '部分证据不足' in row.get('rationale', ''):
            return None
        values = row.get('tier_range') or [row.get('tier')]
        if any(v not in {'B1', 'B2', 'B3', 'B4', 'B5'} for v in values): return None
        return min(int(v[1]) for v in values)

    major_skills = [s for s in skills if s.get('hard')]
    selected_skills = major_skills or skills
    # Never count D4 and its individual skills twice. Where a historical record
    # has no individual skill rows, a fully evidenced D4 remains usable.
    technical = selected_skills or [by_id.get('D4') or {'name': '技能证据'}]
    project = by_id.get('D3') or {'name': '项目经验'}
    rows = [(row, level(row)) for row in [*technical, project]]
    name = lambda row: row.get('skill') or row.get('name') or '项目经验'
    known = sorted(value for _, value in rows if value is not None)
    missing = [name(row) for row, value in rows if value is None]
    strengths = [name(row) for row, value in rows if value is not None and value >= 4]
    gaps = [name(row) for row, value in rows if value is not None and value < 4]
    notes = [d['name'] for d in dimensions if d['dimension_id'] not in {'D3', 'D4'} and level(d) is None]
    if known:
        # Lower ordinal median: no invented overall score, no zero for absence,
        # and no promotion caused by duplicating an aggregate technical dimension.
        median = known[(len(known) - 1) // 2]
        band, label = FIT_BANDS[median]
        reason = {
            5: '从现有证据看，所评估方面充分支持岗位要求，并体现出更深入的相关经历。',
            4: '从现有证据看，所评估方面与岗位要求较为相符。',
            3: '从现有证据看，已有相关经历，所评估方面仍有一定差距。',
            2: '从现有证据看，所评估方面与岗位要求存在较明显差距。',
            1: '从现有证据看，所评估方面与岗位要求存在较大差距。',
        }[median]
    else:
        band, label, reason = 'unassessed', '暂无判断依据', '现有材料暂无可用于对照岗位的技能或项目依据，仅保留提示。'
    return dict(band=band, label=label, reason=reason, strengths=list(dict.fromkeys(strengths)), gaps=list(dict.fromkeys(gaps)),
        missing=list(dict.fromkeys(missing)), additional_missing=notes,
        coverage={'known': len(known), 'total': len(rows)},
        assessed_items=[name(row) for row, value in rows if value is not None],
        policy_version=FIT_POLICY)


def refresh_fit_result(row):
    if isinstance(row.get('dimensions'), list) and isinstance(row.get('skill_levels'), list):
        return {**row, 'fit_summary': fit_summary(row['dimensions'], row['skill_levels'])}
    return dict(row)


def rank_results(results):
    order = {'very_high': 5, 'high': 4, 'medium': 3, 'low': 2, 'very_low': 1}
    normalized = [refresh_fit_result(row) for row in results]
    # Evidence coverage is displayed, never used as an absence penalty. The old
    # sort_key encodes missing dimensions as zero and must not decide this ranking.
    valid = sorted(normalized, key=lambda r: order.get(r.get('fit_summary', {}).get('band'), 0), reverse=True)
    previous, rank = None, 0
    for index, row in enumerate(valid):
        band = row.get('fit_summary', {}).get('band')
        if band != previous: rank = index + 1
        row['rank'] = rank if band in order else None
        if 'dimensions' in row and 'skill_levels' in row: row['basis_statement'] = FIT_BASIS
        previous = band
    return valid


def present_comparison(row):
    # Recompute derived labels from the saved evidence, without changing the
    # source snapshot or triggering a model call. Original records stay intact.
    return {**row, 'ranked_results': rank_results(row.get('ranked_results', [])),
            'display_policy_version': FIT_POLICY,
            'policy_updated': row.get('policy_version') != FIT_POLICY}


def targets_for(svc, data, actor):
    targets = []
    for index, id in enumerate(data.job_ids):
        job = svc.db.get('job_profiles', id)
        if not job or job['status'] != '已确认' or not svc.job_visible(job, actor):
            raise DomainError('NOT_FOUND', '所选岗位已不可访问或尚未确认，请刷新岗位列表。', 404)
        targets.append(dict(job_ref=index + 1, job_id=id, version=job['version'],
            fingerprint=content_hash([job['profile'], job['source_jd'], job['version']])))
    for index, text in enumerate(data.job_texts):
        targets.append(dict(job_ref=index + 1, text=text))
    return targets


def checked_job(svc, target, actor):
    job = svc.db.get('job_profiles', target['job_id'])
    if not job or not svc.job_visible(job, actor) or job['status'] != '已确认':
        raise DomainError('JOB_UNAVAILABLE', '该岗位已不可访问，本次未生成结果。', 409)
    if content_hash([job['profile'], job['source_jd'], job['version']]) != target['fingerprint']:
        raise DomainError('JOB_CHANGED', '岗位要求已更新，请使用最新资料重新分析。', 409)
    return job


def evaluate_target(svc, target, resume, actor):
    if target.get('job_id'):
        job = checked_job(svc, target, actor)
    else:
        text = target['text']
        svc.budget_check()
        job = dict(id='user-paste', title=text.splitlines()[0][:60] or f"岗位 {target['job_ref']}",
            profile=svc.gateway.jd(redact(text), model_id='deepseek'), source_jd=text, version=1)
    payload = svc.evaluate(job, resume, actor)
    if target.get('job_id'): checked_job(svc, target, actor)
    if content_hash(svc.active_resume(resume['id'], actor)['text']) != content_hash(resume['text']):
        raise DomainError('RESUME_CHANGED', '简历已修改，本次未保存过期资料的结果。', 409)
    return dict(job_ref=target['job_ref'], job_id=target.get('job_id'), job_title=job['title'],
        company_name=svc.enterprise_company_name(job.get('owner', '')) if job.get('owner', '').startswith('enterprise:') else '',
        personal_reference=job.get('owner') == actor, profile_version=job['version'],
        dimensions=payload['dimensions'], skill_levels=payload['skill_levels'], sort_key=payload['sort_key'],
        fit_summary=fit_summary(payload['dimensions'], payload['skill_levels']), assessed_at=payload['assessed_at'],
        basis_statement=FIT_BASIS)
