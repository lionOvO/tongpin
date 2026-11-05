"""Human decisions, job-scoped resume consent and immutable application snapshots."""
import hashlib
import json
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .db import now
from .errors import DomainError
from .security import redact
from .deterministic import match_preferences

TERMINAL = {'withdrawn', 'declined', 'rejected', 'closed'}


class ApplyInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    job_id: str = Field(min_length=1, max_length=100)
    resume_id: str = Field(min_length=1, max_length=100)
    expected_job_version: int = Field(ge=1)
    consent_resume: bool
    # Accepted for older clients; saved expectation visibility is authoritative.
    share_preferences: bool | None = None
    introduction: str = Field(default='', max_length=2000)
    request_id: UUID


class HiringAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['invite', 'accept', 'decline', 'reject', 'withdraw', 'close', 'refresh_preferences']
    text: str = Field(default='', max_length=2000)
    expected_version: int = Field(ge=1)
    request_id: UUID


class HiringMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=2000)
    expected_version: int = Field(ge=1)
    request_id: UUID


class ConversationRead(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message_count: int = Field(ge=0, le=200)
    invitation_at: str | None = Field(default=None, max_length=100)


class ApplicationResumeImport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)


class Hiring:
    def __init__(self, service, auth):
        self.svc = service; self.db = service.db; self.auth = auth

    def owned(self, id, actor, cx=None):
        row = self.db.get('applications', id, cx)
        if not row or actor not in {row['owner'], row['candidate_owner']}:
            raise DomainError('NOT_FOUND', '投递记录不存在或无权访问。', 404)
        return row

    def available(self, row):
        job = self.db.get('job_profiles', row['job_id'])
        return bool(job and job.get('moderation_status') != 'suspended'
            and self.svc.enterprise_hiring_enabled(row['owner'])
            and self.auth.actor_active(row['candidate_owner']))

    def shared_resume(self, id, actor, cx=None):
        self.svc.enterprise(actor)
        row = self.owned(id, actor, cx)
        if row['owner'] != actor:
            raise DomainError('NOT_FOUND', '投递记录不存在或无权访问。', 404)
        if row['status'] in TERMINAL or not self.available(row):
            raise DomainError('RESUME_CONSENT_UNAVAILABLE', '这份投递简历的授权已结束或暂停，不能继续下载、导入或分析。', 403)
        return row

    def imported_resume_available(self, resume, cx=None):
        row = self.db.get('applications', resume['source_application_id'], cx)
        return bool(row and row['owner'] == resume['owner']
            and row['job_id'] == resume.get('application_job_id')
            and row['status'] not in TERMINAL and self.available(row))

    def resume_candidates(self, actor, *, job_id=None, offset=0, limit=20, query=''):
        self.svc.enterprise(actor)
        if job_id: self.svc.owned('job_profiles', job_id, actor)
        imports = {r['source_application_id']: r['id'] for r in self.svc.active_resumes(actor) if r.get('source_application_id')}
        rows = [row for row in self.list(actor, job_id) if row['resume_shared']
            and (not query.strip() or any(query.strip().casefold() in row[k].casefold() for k in ('candidate_name', 'job_title')))]
        return {'items': [{**row, 'imported_resume_id': imports.get(row['id'])} for row in rows[offset:offset+limit]],
            'total': len(rows), 'offset': offset, 'limit': limit}

    def import_resume(self, id, data, actor):
        self.svc.writable()
        with self.db.transaction() as cx:
            cx.execute('BEGIN IMMEDIATE')
            row = self.shared_resume(id, actor, cx)
            existing = cx.execute("SELECT * FROM resumes WHERE env=? AND owner=? AND json_extract(payload,'$.source_application_id')=? AND json_extract(payload,'$.deleted_at') IS NULL", (self.svc.settings.env, actor, id)).fetchone()
            if existing: return {'resume': self.svc.public_resume(self.db.decode(existing)), 'already_imported': True}
            self.version(row, data.expected_version)
            snapshot = row['resume_snapshot']
            person = self.db.insert('candidates', {'display_name': snapshot['name']}, actor, row['data_origin'], cx=cx)
            resume = self.db.insert('resumes', {
                'display_name': snapshot['name'], 'text': snapshot['text'], 'parse_status': '成功',
                'source_application_id': id, 'application_job_id': row['job_id'], 'application_job_title': row['job_title'],
                'revision_kind': snapshot.get('revision_kind'), 'self_reported_paragraphs': snapshot.get('self_reported_paragraphs', []),
                'imported_at': now(),
            }, actor, row['data_origin'], cx=cx, candidate_id=person['id'])
            self.db.audit('投递简历导入', {'application_id': id, 'resume_id': resume['id'], 'job_id': row['job_id']}, actor, cx=cx)
        return {'resume': self.svc.public_resume(resume), 'already_imported': False}

    def download_resume(self, id, actor):
        row = self.shared_resume(id, actor)
        self.db.audit('投递简历下载', {'application_id': id, 'job_id': row['job_id']}, actor)
        return row['resume_snapshot']

    @staticmethod
    def preference(row):
        if not row or not row.get('share_with_counterparty'): return None
        return {**{key: row[key] for key in ('id', 'dimensions', 'dimension_version', 'ambience_text')},
            'dimension_labels': {d['id']: d['name'] for d in row.get('dimension_snapshot', {}).get('dimensions', [])}}

    def public(self, row, actor, detail=False):
        available = self.available(row)
        shared = row['status'] not in TERMINAL and available
        result = {key: row[key] for key in ('id', 'job_id', 'status', 'version', 'created_at', 'updated_at', 'job_title', 'company_name', 'candidate_name')}
        result.update({'available': available, 'resume_shared': shared, 'resume_name': row['resume_snapshot']['name'],
            'message_count': len(row['messages']), 'invitation': row.get('invitation')})
        side = 'candidate' if actor == row['candidate_owner'] else 'enterprise'
        visible_messages = row['messages'] if side == 'candidate' or available else []
        read_count = row.get('message_reads', {}).get(side, 0)
        unread = sum(m['side'] != side for m in visible_messages[read_count:])
        if side == 'candidate' and row['status'] == 'invited' and not row.get('invitation_seen', False):
            unread += 1
        result.update({'unread_count': unread, 'last_message': visible_messages[-1] if visible_messages else None})
        if actor == row['owner']:
            review = row.get('recruiter_review') if shared else None
            result['review_strengths'] = [s['title'] for s in (review or {}).get('strengths', []) if s['evidence_kind'] == 'experience']
            result['review_ready'] = bool(review)
            result['ai_message_count'] = (len(row.get('recruiter_chat', [])) + sum(len(s.get('messages', [])) for s in row.get('recruiter_chat_archives', []))) if shared else 0
        if not detail: return result
        mine = actor == row['candidate_owner']
        cand_latest = self.svc.latest_preference('candidate', row['resume_id'])
        ent_latest = self.svc.latest_preference('enterprise', row['job_id'])
        if shared:
            cand = self.preference(cand_latest)
            ent = self.preference(ent_latest)
        else:
            # Keep closed application snapshots, but never expose an expectation
            # whose owner subsequently made it private.
            cand = row.get('candidate_preferences') if mine and cand_latest and cand_latest['share_with_counterparty'] else None
            ent = row.get('enterprise_preferences') if ent_latest and ent_latest['share_with_counterparty'] else None
        result.update({'resume_id': row['resume_id'] if mine else None, 'events': row['events'],
            'job_snapshot': row['job_snapshot'], 'introduction': row['introduction'],
            'messages': row['messages'] if mine or available else [],
            'resume_snapshot': row['resume_snapshot'] if mine or shared else None,
            'candidate_preferences': cand,
            'enterprise_preferences': ent})
        result['preference_comparison'] = None
        result['preference_notice'] = '双方尚未都填写并公开期待，可先沟通。公开设置在“我的期待”中统一管理，保存后自动同步。'
        ent, cand = result['enterprise_preferences'], result['candidate_preferences']
        if ent and cand:
            try:
                result['preference_comparison'] = match_preferences(ent, cand, self.svc.config.get('preferences'))
                result['preference_notice'] = '按双方在“我的期待”中保存的公开设置自动展示，仅供双方参考。'
            except DomainError:
                result['preference_notice'] = '期待填写口径已更新，请双方在“我的期待”中重新保存。'
        return result

    def list(self, actor, job_id=None):
        with self.db.transaction() as cx:
            field = "json_extract(payload,'$.candidate_owner')" if actor.startswith('candidate:') else 'owner'
            sql = f"SELECT * FROM applications WHERE env=? AND {field}=?"
            params = [self.svc.settings.env, actor]
            if job_id: sql += ' AND job_id=?'; params.append(job_id)
            order = "json_extract(payload,'$.updated_at')" if actor.startswith('candidate:') else 'created_at'
            rows = [self.db.decode(r) for r in cx.execute(sql+f" ORDER BY {order} DESC,id",params)]
        return [self.public(row, actor) for row in rows]

    def page(self, actor, *, offset=0, limit=30, job_id=None, query='', status='all', conversations=False):
        field = "json_extract(payload,'$.candidate_owner')" if actor.startswith('candidate:') else 'owner'
        sql=f'SELECT * FROM applications WHERE env=? AND {field}=?'
        params=[self.svc.settings.env,actor]
        if job_id: sql+=' AND job_id=?'; params.append(job_id)
        if conversations: sql+=" AND (json_extract(payload,'$.invitation') IS NOT NULL OR json_array_length(payload,'$.messages')>0)"
        if status=='ended': sql+=" AND json_extract(payload,'$.status') IN ('withdrawn','declined','rejected','closed')"
        elif status!='all': sql+=" AND json_extract(payload,'$.status')=?";params.append(status)
        if query.strip():
            # Match the entire authorized history before applying the page limit.
            phrase=query.strip().casefold()
            with self.db.transaction() as cx: raw=[self.db.decode(r) for r in cx.execute(sql,params)]
            found=[]
            for row in raw:
                searchable=[row['company_name'],row['candidate_name'],row['job_title']]
                if conversations:
                    searchable.append((row.get('invitation') or {}).get('text',''))
                    if actor==row['candidate_owner'] or self.available(row): searchable += [m['text'] for m in row['messages']]
                if any(phrase in text.casefold() for text in searchable): found.append(row)
            found.sort(key=lambda r:(r['updated_at'],r['id']),reverse=True)
            total=len(found); rows=found[offset:offset+limit]
        else:
            with self.db.transaction() as cx:
                total=cx.execute('SELECT COUNT(*) FROM ('+sql+')',params).fetchone()[0]
                rows=[self.db.decode(r) for r in cx.execute(sql+" ORDER BY json_extract(payload,'$.updated_at') DESC,id DESC LIMIT ? OFFSET ?",[*params,limit,offset])]
        return {'items':[self.public(row,actor) for row in rows],'total':total,'offset':offset,'limit':limit}

    def unread_total(self, actor):
        side='candidate' if actor.startswith('candidate:') else 'enterprise'
        field="json_extract(a.payload,'$.candidate_owner')" if side=='candidate' else 'a.owner'
        with self.db.transaction() as cx:
            # Read cursors apply to the complete history, independent of list pages.
            rows=cx.execute(f"""SELECT a.owner,json_extract(a.payload,'$.candidate_owner') AS candidate,
                a.job_id,(SELECT COUNT(*) FROM json_each(a.payload,'$.messages') m
                    WHERE CAST(m.key AS INTEGER)>=COALESCE(json_extract(a.payload,'$.message_reads.{side}'),0)
                    AND json_extract(m.value,'$.side')!=?) +
                CASE WHEN ?='candidate' AND json_extract(a.payload,'$.status')='invited'
                    AND NOT COALESCE(json_extract(a.payload,'$.invitation_seen'),0) THEN 1 ELSE 0 END AS unread
                FROM applications a WHERE a.env=? AND {field}=?""",(side,side,self.svc.settings.env,actor)).fetchall()
        total=0
        for row in rows:
            if not row['unread']: continue
            if side=='enterprise':
                job=self.db.get('job_profiles',row['job_id'])
                if not job or job.get('moderation_status')=='suspended' or not self.svc.enterprise_hiring_enabled(row['owner']) or not self.auth.actor_active(row['candidate']): continue
            total+=row['unread']
        return total

    def conversations(self, actor, query=''):
        # Review ordering is independent; the inbox sorts by actual activity.
        rows = [r for r in self.list(actor) if r['invitation'] or r['message_count']]
        if query.strip():
            phrase = query.strip().casefold()
            matches = []
            for summary in rows:
                row = self.owned(summary['id'], actor)
                messages = row['messages'] if actor == row['candidate_owner'] or summary['available'] else []
                searchable = [summary['company_name'], summary['candidate_name'], summary['job_title'],
                    (summary.get('invitation') or {}).get('text', ''), *[m['text'] for m in messages]]
                if any(phrase in text.casefold() for text in searchable): matches.append(summary)
            rows = matches
        return sorted(rows, key=lambda r: (r['updated_at'], r['id']), reverse=True)

    def read(self, id, data, actor):
        self.svc.writable()
        with self.db.transaction() as cx:
            cx.execute('BEGIN IMMEDIATE')
            row = self.owned(id, actor, cx)
            if data.message_count > len(row['messages']):
                raise DomainError('CONVERSATION_CURSOR', '沟通记录已变化，请重新加载。', 409)
            side = 'candidate' if actor == row['candidate_owner'] else 'enterprise'
            if side == 'enterprise' and not self.available(row):
                raise DomainError('APPLICATION_UNAVAILABLE', '当前授权不可用。', 403)
            reads = row.get('message_reads', {})
            patch = {'message_reads': {**reads, side: max(reads.get(side, 0), data.message_count)}}
            invitation = row.get('invitation')
            if side == 'candidate' and invitation and data.invitation_at == invitation['created_at']:
                patch['invitation_seen'] = True
            # Reading must not change business version, activity time or the other side's cursor.
            result = self.db.update('applications', id, patch, cx)
        return self.public(result, actor, True)

    @staticmethod
    def fingerprint(data):
        value = data.model_dump(mode='json', exclude={'expected_version', 'request_id'})
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    @staticmethod
    def version(row, expected):
        if row['version'] != expected:
            raise DomainError('APPLICATION_CONFLICT', '投递进展已更新，请刷新后再操作。', 409)

    def apply(self, data, actor):
        self.svc.candidate(actor); self.svc.writable()
        if not data.consent_resume:
            raise DomainError('APPLICATION_CONSENT', '请明确同意向这个岗位的企业共享所选简历。', 422)
        fingerprint = self.fingerprint(data)
        with self.db.transaction() as cx:
            cx.execute('BEGIN IMMEDIATE')
            mine = [self.db.decode(r) for r in cx.execute("SELECT * FROM applications WHERE env=? AND json_extract(payload,'$.candidate_owner')=?", (self.svc.settings.env,actor))]
            previous = next((r for r in mine if r.get('apply_request_id') == str(data.request_id)), None)
            if previous:
                if previous['apply_fingerprint'] != fingerprint:
                    raise DomainError('APPLICATION_REQUEST_CHANGED', '此次投递已保存，请重新打开投递窗口。', 409)
                return self.public(previous, actor, True)
            job = self.db.get('job_profiles', data.job_id, cx)
            resume = self.db.get('resumes', data.resume_id, cx)
            if not job or not job['owner'].startswith('enterprise:') or not self.svc.job_visible(job, actor) or not self.svc.enterprise_hiring_enabled(job['owner']):
                raise DomainError('APPLICATION_JOB_UNAVAILABLE', '该企业岗位暂不可投递，请选择已公开的认证企业岗位。', 404)
            if not resume or resume['owner'] != actor or resume.get('deleted_at'):
                raise DomainError('NOT_FOUND', '所选简历不存在或无权访问。', 404)
            if job['version'] != data.expected_job_version:
                raise DomainError('APPLICATION_JOB_CHANGED', '岗位要求已更新，请重新查看后再投递。', 409)
            existing = next((r for r in mine if r['job_id'] == job['id'] and r['status'] not in TERMINAL), None)
            if existing:
                raise DomainError('APPLICATION_EXISTS', '你已投递这个岗位，请到“我的投递”查看进展。', 409)
            if len(mine) >= 1000:
                raise DomainError('APPLICATION_LIMIT', '当前账号最多保留 1000 份投递。', 422)
            cand = self.preference(self.svc.latest_preference('candidate', resume['id']))
            ent = self.preference(self.svc.latest_preference('enterprise', job['id']))
            stamp = now()
            row = self.db.insert('applications', {'candidate_owner': actor, 'apply_request_id': str(data.request_id),
                'apply_fingerprint': fingerprint, 'job_title': job['title'], 'company_name': self.svc.enterprise_company_name(job['owner']),
                'candidate_name': resume['display_name'], 'resume_snapshot': {'name': resume['display_name'], 'text': resume['text'],
                    'revision_kind': resume.get('revision_kind'), 'self_reported_paragraphs': resume.get('self_reported_paragraphs', [])},
                'job_snapshot': {'title': job['title'], 'text': redact(job['source_jd']), 'version': job['version']},
                'candidate_preferences': cand, 'enterprise_preferences': ent, 'introduction': redact(data.introduction).strip(),
                'consent': {'resume': True, 'preferences': bool(cand), 'preference_policy': 'saved_visibility', 'accepted_at': stamp},
                'status': 'submitted', 'version': 1, 'updated_at': stamp, 'invitation': None,
                'events': [{'action': 'apply', 'side': 'candidate', 'text': '投递简历并授权该岗位企业查看。', 'created_at': stamp}],
                'messages': [], 'requests': {}}, job['owner'], 'real' if 'real' in {resume['data_origin'], job['data_origin']} else 'synthetic',
                cx=cx, job_id=job['id'], resume_id=resume['id'])
            self.db.audit('求职者投递', {'application_id': row['id'], 'job_id': job['id']}, actor, cx=cx)
        return self.public(row, actor, True)

    def change(self, id, data, actor, message=False):
        self.svc.writable()
        fingerprint = self.fingerprint(data)
        with self.db.transaction() as cx:
            cx.execute('BEGIN IMMEDIATE')
            row = self.owned(id, actor, cx)
            prior = row['requests'].get(str(data.request_id))
            if prior:
                if prior['fingerprint'] != fingerprint or prior['message'] != message:
                    raise DomainError('APPLICATION_REQUEST_CHANGED', '此次操作已完成，请刷新投递记录。', 409)
                return self.public(row, actor, True)
            self.version(row, data.expected_version)
            side = 'candidate' if actor == row['candidate_owner'] else 'enterprise'
            action = 'message' if message else data.action
            text = redact(data.text).strip()
            if not self.available(row) and not (action == 'withdraw' and side == 'candidate'):
                raise DomainError('APPLICATION_UNAVAILABLE', '岗位或账号已被暂停，当前无法继续沟通。', 403)
            if row['status'] in TERMINAL:
                raise DomainError('APPLICATION_STATE', '此投递已结束，无法继续操作。', 409)
            allowed = {'enterprise': {'invite', 'reject', 'close', 'refresh_preferences', 'message'},
                'candidate': {'accept', 'decline', 'withdraw', 'close', 'refresh_preferences', 'message'}}
            if action not in allowed[side]:
                raise DomainError('APPLICATION_ROLE', '当前身份不能执行这个操作。', 403)
            states = {'invite': {'submitted'}, 'accept': {'invited'}, 'decline': {'invited'},
                'reject': {'submitted', 'invited'}, 'close': {'accepted'}, 'message': {'accepted'},
                'withdraw': {'submitted', 'invited', 'accepted'}, 'refresh_preferences': {'submitted', 'invited', 'accepted'}}
            if row['status'] not in states[action]:
                raise DomainError('APPLICATION_STATE', '当前进展不能执行这个操作，请刷新后查看。', 409)
            if action in {'invite', 'message'} and len(text) < 2:
                raise DomainError('APPLICATION_TEXT', '请填写至少两个字的邀请或沟通内容。', 422)
            stamp = now(); patch = {'version': row['version'] + 1, 'updated_at': stamp}
            if action == 'refresh_preferences':
                target = row['resume_id'] if side == 'candidate' else row['job_id']
                pref = self.preference(self.svc.latest_preference(side, target))
                if not pref:
                    raise DomainError('APPLICATION_PREFERENCE', '请先填写并同意共享期待，再同步到本次投递。', 422)
                patch[side + '_preferences'] = pref
                if side == 'candidate': patch['consent'] = {**row['consent'], 'preferences': True, 'preferences_updated_at': stamp}
                patch['events'] = row['events'] + [{'action': action, 'side': side, 'text': '同步本人最新保存并同意共享的期待。', 'created_at': stamp}]
            elif action == 'message':
                if len(row['messages']) >= 200:
                    raise DomainError('APPLICATION_MESSAGE_LIMIT', '本次沟通已达到 200 条消息。', 422)
                patch['messages'] = row['messages'] + [{'side': side, 'text': text, 'created_at': stamp}]
                patch['message_reads'] = {**row.get('message_reads', {}), side: len(patch['messages'])}
            else:
                patch['status'] = {'invite': 'invited', 'accept': 'accepted', 'decline': 'declined', 'reject': 'rejected', 'withdraw': 'withdrawn', 'close': 'closed'}[action]
                if patch['status'] in TERMINAL:
                    patch.update({'recruiter_review': None, 'recruiter_review_running': None, 'recruiter_review_until': 0,
                        'recruiter_chat': [], 'recruiter_chat_running': None, 'recruiter_chat_until': 0,
                        'recruiter_agent_run': None,
                        'recruiter_chat_context': '', 'recruiter_chat_requests': {}, 'recruiter_chat_archives': [],
                        'recruiter_interview_plan': [], 'recruiter_interview_notes': '', 'recruiter_workspace_requests': {}})
                if action == 'invite': patch['invitation'] = {'text': text, 'created_at': stamp}
                patch['events'] = row['events'] + [{'action': action, 'side': side, 'text': text, 'created_at': stamp}]
            patch['requests'] = {**row['requests'], str(data.request_id): {'fingerprint': fingerprint, 'message': message}}
            result = self.db.update('applications', id, patch, cx)
            self.db.audit('投递沟通进展', {'application_id': id, 'action': action, 'side': side}, actor, cx=cx)
        return self.public(result, actor, True)
