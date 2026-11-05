import csv
import hashlib
import io
import json
import re
from contextvars import ContextVar
from collections import Counter
from pathlib import Path
from .agents import AgentGateway
from .model_catalog import ModelCatalog
from .configuration import Configuration
from .db import Database, TABLES, now
from .deterministic import gpa_tier, skill_tier, d4_result, dimension_result, sort_key, key_tuple, match_preferences, mentions, presentation_violations, rationale_for_display
from .errors import DomainError
from .models import JobProfile
from .retrieval import LocalRetrieval
from .security import redact
from .job_fit import fit_summary, targets_for, evaluate_target, rank_results, FIT_POLICY

QUESTIONS = [
 {"id":"purpose","question":"这次招聘主要解决什么问题？","options":["补充团队能力","支持新业务","人员补充","不清楚 / 跳过"]},
 {"id":"success","question":"半年后，最希望看到什么成果？","options":["独立负责交付","改善产品或性能","支撑团队协作","不清楚 / 跳过"]},
 {"id":"essential","question":"哪些要求源于当前业务需要？","options":["核心技术栈","相关项目经历","相关实践经历","不清楚 / 跳过"]},
 {"id":"trainable","question":"哪些方面可以在入职后继续培养？","options":["技术细节","业务知识","协作方式","不清楚 / 跳过"]},
 {"id":"source","question":"这些要求主要来自哪里？","options":["团队能力缺口","业务需要","合规或硬性制度","模板惯性","不清楚 / 跳过"]}
]
current_actor = ContextVar("current_actor", default="system")


class TalentService:
    def __init__(self, settings):
        self.settings = settings
        self.db = Database(settings)
        self.config = Configuration(settings.data_dir)
        self.models = ModelCatalog(settings)
        self.gateway = AgentGateway(settings, self.record_call, self.models)
        self.retrieval = LocalRetrieval(settings)
        self.maintenance = False
        self.enterprise_owner_verified = lambda actor: False
        self.enterprise_company_name = lambda actor: ''
        self.enterprise_hiring_enabled = lambda actor: False
        self.application_resume_available = lambda resume, cx=None: False

    def enterprise(self, actor):
        if not actor.startswith("enterprise:"):
            raise DomainError("ROLE_REQUIRED", "此操作仅供企业工作台使用", 403)

    def candidate(self, actor):
        if not actor.startswith("candidate:"):
            raise DomainError("ROLE_REQUIRED", "此操作仅供求职者使用", 403)

    def owned(self, table, id, actor):
        obj = self.db.get(table,id)
        if not obj or obj["owner"] != actor:
            raise DomainError("NOT_FOUND", "记录不存在或当前视角无权访问", 404)
        if not self.material_visible(obj):
            raise DomainError('RESUME_CONSENT_UNAVAILABLE', '简历授权已结束或暂停，相关材料与分析不再可查看。', 403)
        return obj

    def material_visible(self, record, cx=None):
        if record.get('source_event_id'):
            event = self.db.get('review_events', record['source_event_id'], cx)
            report = self.db.get('ability_reports', event['report_id'], cx) if event else None
            if report and not self.material_visible(report, cx): return False
        resume = record if record.get('source_application_id') else self.db.get('resumes', record['resume_id'], cx) if record.get('resume_id') else None
        return not resume or not resume.get('source_application_id') or self.application_resume_available(resume, cx)

    def visible_material_records(self, table, actor, **refs):
        return [r for r in self.db.list(table, owner=actor, **refs) if self.material_visible(r)]

    def resume_job_scope(self, resume, job_id):
        if resume.get('source_application_id') and resume.get('application_job_id') != job_id:
            raise DomainError('RESUME_JOB_SCOPE', '投递简历仅用于求职者授权的原岗位，请切换到对应岗位。', 403)

    def writable(self):
        if self.maintenance:
            raise DomainError("MAINTENANCE", "数据维护中，请稍后再试", 503)

    def job_visible(self, job, actor):
        return job["owner"] == actor or (actor.startswith("candidate:") and job["owner"].startswith("enterprise:") and job["status"] == "已确认" and job.get("published") is True and job.get('moderation_status') != 'suspended' and self.enterprise_owner_verified(job["owner"]))

    def public_job(self, job, actor):
        metadata = {'accepts_applications': job['owner'].startswith('enterprise:') and self.job_visible(job, actor)
            and job.get('published') is True and job.get('moderation_status') != 'suspended'
            and self.enterprise_hiring_enabled(job['owner']), 'company_name': self.enterprise_company_name(job['owner']),
            'personal_reference': job['owner'] == actor and actor.startswith('candidate:')}
        if job["owner"] == actor: return {**job, **metadata}
        return {**{key:job[key] for key in ("id","title","source_jd","profile","version","status","published","data_origin")}, **metadata}

    def budget_check(self):
        spent = sum(a["detail"].get("cost_cny",0) for a in self.db.list("audit_logs") if a["event_type"] == "Agent 调用")
        if spent >= self.settings.budget:
            raise DomainError("COST_BUDGET", "当前环境 AI 成本预算已用完，请调整预算或改用演示模式", 429)

    def record_call(self, detail):
        self.db.audit("Agent 调用", detail, owner=current_actor.get(), result=detail.pop("result", "正常"))

    def create_job(self, data, actor):
        self.writable(); self.enterprise(actor); self.budget_check()
        profile = JobProfile.model_validate(data.manual_profile).model_dump() if data.manual_profile else self.gateway.jd(redact(data.jd))
        if any(r["quote"] not in data.jd for r in profile["requirements"]): raise DomainError("EVIDENCE_INVALID","要求必须引用 JD 原文")
        job = self.db.insert("job_profiles", {"title":data.title,"source_jd":data.jd,"profile":profile,"version":1,"status":"待确认","published":False,"history":[],"mode":self.settings.llm_mode},actor,data.data_origin)
        self.db.audit("岗位创建", {"job_id":job["id"],"profile_version":1},actor)
        return job

    def create_reference_job(self, data, actor):
        self.writable(); self.candidate(actor)
        jd = redact(data.jd).strip()
        if len(jd) < 20:
            raise DomainError('REFERENCE_EMPTY', '隔离联系方式后岗位描述不足 20 字，请填写完整职责和要求。', 422)
        fingerprint = hashlib.sha256(json.dumps([data.title, jd, data.data_origin], ensure_ascii=False).encode()).hexdigest()
        def existing(cx=None):
            if cx is not None:
                rows = [self.db.decode(r) for r in cx.execute(
                    'SELECT * FROM job_profiles WHERE env=? AND owner=?', (self.settings.env, actor)).fetchall()]
            else:
                rows = self.db.list('job_profiles', owner=actor)
            return next((j for j in rows if j.get('reference_fingerprint') == fingerprint), None)
        previous = existing()
        if previous: return self.public_job(previous, actor)
        self.budget_check()
        profile = self.gateway.jd(jd, model_id='deepseek')
        if any(r['quote'] not in jd for r in profile['requirements']):
            raise DomainError('EVIDENCE_INVALID', '岗位要求未能对应原文，请调整描述后重试。', 422)
        with self.db.transaction() as cx:
            cx.execute('BEGIN IMMEDIATE')
            previous = existing(cx)
            if previous: return self.public_job(previous, actor)
            job = self.db.insert('job_profiles', {'title': data.title, 'source_jd': jd, 'profile': profile,
                'version': 1, 'status': '已确认', 'published': False, 'source_type': 'user_paste', 'history': [],
                'mode': self.settings.llm_mode, 'reference_fingerprint': fingerprint}, actor, data.data_origin, cx=cx)
            self.db.audit('个人岗位参照添加', {'job_id': job['id']}, actor, cx=cx)
        return self.public_job(job, actor)

    def confirm_job(self, id, data, actor):
        self.writable(); self.enterprise(actor)
        job = self.owned("job_profiles",id,actor)
        if job["version"] != data.expected_version:
            raise DomainError("VERSION_CONFLICT", "画像已被更新，请刷新后重新确认",409)
        profile = data.profile.model_dump()
        if any(r["quote"] not in job["source_jd"] for r in profile["requirements"]):
            raise DomainError("EVIDENCE_INVALID", "每条技能要求必须引用 JD 中的原文",422)
        history = job["history"] + [{"version":job["version"],"profile":job["profile"],"status":job["status"]}]
        with self.db.transaction() as cx:
            fresh = self.db.get("job_profiles",id,cx)
            if fresh["version"] != data.expected_version: raise DomainError("VERSION_CONFLICT","画像版本冲突",409)
            result = self.db.update("job_profiles",id,{"profile":profile,"status":"已确认","version":job["version"]+1,"history":history,"confirmed_at":now()},cx)
            self.db.audit("画像确认",{"job_id":id,"version":result["version"]},actor,cx=cx)
        return result

    def create_resume(self, data, actor, original_file=None):
        self.writable()
        safe = redact(data.text)
        if len(safe.strip()) < 10: raise DomainError("NO_USABLE_TEXT", "剥离个人信息后没有足够的简历内容",422)
        if self.settings.vector: self.retrieval.initialize()
        folder = self.settings.data_dir / "raw_files"
        folder.mkdir(exist_ok=True)
        raw_path = None
        original_path = None
        try:
            with self.db.transaction() as cx:
                candidate = self.db.insert("candidates", {"display_name":data.name},actor,data.data_origin,cx=cx)
                raw_path = folder / (candidate["id"] + ".txt")
                raw_path.write_text(data.text,encoding="utf-8")
                source = {}
                if original_file is not None:
                    filename, content = original_file
                    filename = re.split(r'[/\\]', filename)[-1]
                    filename = ''.join(c for c in filename if ord(c) >= 32 and c != '\x7f')
                    suffix = Path(filename).suffix.lower()
                    filename = Path(filename).stem[:170] + suffix
                    media_types = {'.doc': 'application/msword', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.pdf': 'application/pdf', '.txt': 'text/plain', '.json': 'application/json'}
                    if suffix not in media_types:
                        raise DomainError('FILE_TYPE', '仅支持 PDF、JSON 和 TXT', 422)
                    original_path = folder / (candidate['id'] + '.original' + suffix)
                    original_path.write_bytes(content)
                    source = {'original_file_key': original_path.name,
                              'original_file': {'name': filename, 'media_type': media_types[suffix], 'size': len(content)}}
                resume = self.db.insert("resumes", {"display_name":data.name,"text":safe,"raw_file_path":str(raw_path),"parse_status":"成功","source_hash":hashlib.sha256(data.text.encode()).hexdigest(), **source},actor,data.data_origin,cx=cx,candidate_id=candidate["id"])
                self.db.audit("简历导入",{"resume_id":resume["id"],"data_origin":data.data_origin},actor,cx=cx)
        except Exception:
            if raw_path is not None:
                try: raw_path.unlink(missing_ok=True)
                except OSError: pass
            if original_path is not None:
                try: original_path.unlink(missing_ok=True)
                except OSError: pass
            raise
        try:
            self.retrieval.upsert(resume)
        except Exception as exc:
            self.db.audit("向量索引失败",{"resume_id":resume["id"],"error_type":type(exc).__name__},actor,"告警")
        return self.public_resume(resume)

    def public_resume(self, resume):
        return {k:v for k,v in resume.items() if k not in {"raw_file_path","source_hash","original_file_key"}}

    def resume_original(self, id, actor):
        resume = self.active_resume(id, actor)
        metadata = resume.get('original_file')
        key = resume.get('original_file_key', '')
        folder = (self.settings.data_dir / 'raw_files').resolve()
        path = (folder / key).resolve()
        if not metadata or not key or path.parent != folder or not path.is_file():
            raise DomainError('ORIGINAL_UNAVAILABLE', '这份简历未保留原文件，或文件已不可用。请重新导入原文件。', 404)
        return path, metadata

    def active_resumes(self, actor):
        return [r for r in self.db.list("resumes", owner=actor) if not r.get("deleted_at") and self.material_visible(r)]

    def active_resume(self, id, actor, cx=None):
        resume = self.db.get("resumes", id, cx)
        if not resume or resume["owner"] != actor or resume.get("deleted_at"):
            raise DomainError("NOT_FOUND", "简历不存在、已删除或当前身份无权访问。", 404)
        if not self.material_visible(resume, cx):
            raise DomainError('RESUME_CONSENT_UNAVAILABLE', '简历授权已结束或暂停，不能继续分析。', 403)
        return resume

    def delete_resume(self, id, actor):
        self.writable()
        # Retain referenced history and immutable application snapshots. Deleting a
        # library item must not silently revoke consent or destroy a conversation.
        with self.db.transaction() as cx:
            cx.execute("BEGIN IMMEDIATE")
            resume = self.db.get("resumes", id, cx)
            if not resume or resume["owner"] != actor:
                raise DomainError("NOT_FOUND", "简历不存在或当前身份无权访问。", 404)
            if not resume.get("deleted_at"):
                self.db.update("resumes", id, {"deleted_at": now()}, cx)
                self.db.audit("简历删除", {"resume_id": id, "history_retained": True}, actor, cx=cx)
        return {"id": id, "deleted": True, "history_retained": True}

    def latest_preference(self, side, id):
        rows = self.db.list("preference_submissions", **({"job_id":id} if side == "enterprise" else {"resume_id":id}))
        return next((r for r in rows if r["side"] == side),None)

    def submit_preference(self, data, actor):
        self.writable()
        if data.side == "enterprise":
            self.enterprise(actor)
            if not data.job_id or data.resume_id: raise DomainError("PREFERENCE_TARGET", "企业填报只关联一个岗位")
            obj = self.owned("job_profiles",data.job_id,actor)
            if obj["status"] != "已确认": raise DomainError("PROFILE_UNCONFIRMED","请先确认岗位画像")
        else:
            self.candidate(actor)
            if not data.resume_id or data.job_id or data.ambience_text: raise DomainError("PREFERENCE_TARGET", "个人填报只关联本人简历，不填写企业氛围")
            obj = self.active_resume(data.resume_id,actor)
        cfg = self.config.get("preferences")
        if data.dimension_version != cfg["version"]: raise DomainError("DIMENSION_VERSION_MISMATCH","维度口径已更新，请刷新后重新填写")
        dims = {d["id"]:d for d in cfg["dimensions"]}
        if set(data.dimensions) - set(dims): raise DomainError("UNKNOWN_DIMENSION", "填报包含未知维度")
        for id, d in dims.items():
            if d["required"] and id not in data.dimensions: raise DomainError("REQUIRED_DIMENSION", "请完成三项必填偏好；允许选择无法判断")
            value = data.dimensions.get(id)
            if value is not None and value not in d["options"]: raise DomainError("INVALID_OPTION", "偏好必须使用当前维度表提供的选项")
        payload = data.model_dump(exclude={"job_id","resume_id"})
        payload["unfilled_dims"] = [id for id in dims if not data.dimensions.get(id)]
        payload["dimension_snapshot"] = cfg
        refs = {"job_id":data.job_id,"resume_id":data.resume_id}
        row = self.db.insert("preference_submissions",payload,actor,obj["data_origin"],**refs)
        self.db.audit("偏好填报",{"submission_id":row["id"],"dimension_version":cfg["version"]},actor)
        return row

    def run_match(self, data, actor):
        self.writable()
        presentation = self.config.get('presentation')
        if any(any(term not in presentation.get(key, '') for term in ('可能存在偏差', '系统不设合格线')) for key in ('bias_notice', 'footer')):
            self.db.audit('报告呈现阻断', {'reason': '偏好结果首屏或页脚提示不完整'}, actor, '告警')
            raise DomainError('NOTICE_REQUIRED', '报告生成未完成，请重试', 422)
        job, resume = self.db.get("job_profiles",data.job_id), self.db.get("resumes",data.resume_id)
        if not job or not resume or resume.get("deleted_at") or actor not in {job["owner"],resume["owner"]}: raise DomainError("NOT_FOUND","无法访问此次对照",404)
        previous = self.db.list("match_results",job_id=job["id"],resume_id=resume["id"])
        applications = self.db.list('applications', job_id=job['id'], resume_id=resume['id'])
        active = next((a for a in applications if a['status'] not in {'withdrawn','declined','rejected','closed'}), None)
        if actor == resume["owner"]:
            if not self.job_visible(job,actor): raise DomainError("NOT_FOUND","目标岗位不可访问",404)
            if not active and not previous and not data.share_with_job: raise DomainError("SHARING_REQUIRED","请明确同意向此岗位招聘方共享姓名与本次偏好对照依据",403)
        if job["status"] != "已确认": raise DomainError("PROFILE_UNCONFIRMED","请先确认岗位画像")
        ent = self.latest_preference("enterprise",job["id"])
        cand = self.latest_preference("candidate",resume["id"])
        if any(pref and not pref['share_with_counterparty'] for pref in (ent, cand)):
            raise DomainError('SHARING_REQUIRED', '一方的期待设为仅自己可见，请在“我的期待”中调整公开设置后再对照。', 403)
        if actor == resume['owner'] and resume['owner'] != job['owner']:
            if not active and not data.share_with_job and not any(m['cand_submission_id'] == (cand or {}).get('id') for m in previous):
                raise DomainError('SHARING_REQUIRED', '新期待需要重新确认向此岗位共享。', 403)
        elif resume['owner'] != actor:
            # Old matches authorize their exact snapshot, never all future submissions.
            if applications and not active:
                raise DomainError('NOT_FOUND', '此岗位的共享授权已结束，可查看历史对照。', 404)
            if not active:
                shared_id = previous[0]['cand_submission_id'] if previous else None
                cand = self.db.get('preference_submissions', shared_id) if shared_id else None
            if not cand:
                raise DomainError('NOT_FOUND', '该求职者尚未授权共享本次期待。', 404)
        if not ent or not cand: raise DomainError("PREFERENCE_MISSING","请双方先完成偏好填报")
        if not ent["share_with_counterparty"] or not cand["share_with_counterparty"]: raise DomainError("SHARING_REQUIRED","双方尚未同意共享对照依据",403)
        preference_config=self.config.get("preferences")
        result = match_preferences(ent,cand,preference_config)
        result.update({"rubric_version":self.config.get("rubric")["version"],"job_title":job["title"],"candidate_name":resume["display_name"],"enterprise_owner":job["owner"],"candidate_owner":resume["owner"],"ambience_text":ent["ambience_text"],"ent_snapshot":ent["dimensions"],"cand_snapshot":cand["dimensions"]})
        existing = next((m for m in self.db.list("match_results",job_id=job["id"],resume_id=resume["id"]) if m["ent_submission_id"]==ent["id"] and m["cand_submission_id"]==cand["id"] and m["engine_version"]==result["engine_version"]),None)
        if existing: return existing
        origin = "synthetic" if "synthetic" in {job["data_origin"],resume["data_origin"]} else "real"
        row = self.db.insert("match_results",result,job["owner"],origin,job_id=job["id"],resume_id=resume["id"],ent_submission_id=ent["id"],cand_submission_id=cand["id"])
        self.db.audit("偏好对照",{"match_id":row["id"],"engine_version":result["engine_version"]},actor)
        return row

    def visible_matches(self, actor):
        rows = [m for m in self.db.list("match_results") if actor in {m["enterprise_owner"],m["candidate_owner"]}]
        visible = []
        for row in rows:
            a = self.latest_preference("enterprise",row["job_id"])
            b = self.latest_preference("candidate",row["resume_id"])
            if any(pref and not pref['share_with_counterparty'] for pref in (a, b)):
                continue
            row["outdated"] = not a or not b or a["id"] != row["ent_submission_id"] or b["id"] != row["cand_submission_id"] or row["dimension_version"]!=self.config.get("preferences")["version"]
            visible.append(row)
        return visible

    def evaluate(self, job, resume, actor):
        self.budget_check()
        rubric, priorities = self.config.get("rubric"), self.config.get("priorities")
        presentation = self.config.get('presentation')
        if any(any(term not in presentation.get(key, '') for term in ('可能存在偏差', '系统不设合格线')) for key in ('bias_notice', 'footer')):
            self.db.audit('报告呈现阻断', {'reason': '首屏或页脚偏差提示不完整'}, actor, '告警')
            raise DomainError('NOTICE_REQUIRED', '报告生成未完成，请重试', 422)
        memory = [redact(m["pattern"]) for m in self.visible_material_records("calibration_memory",actor,job_id=job["id"]) if m["confirmed"] and not m.get("deleted_at")]
        brief = self.current_brief(job)
        obj = self.gateway.evaluate(redact(resume["text"]),job["profile"],rubric,memory,major_map=self.config.get('major-map'),hiring_brief=brief)
        requirement_context = {r['content'].casefold():r for r in (brief or {}).get('requirements', []) if r.get('origin')=='JD原文'}
        skills_by_name = {s["skill"].lower():s for s in obj["skills"]}
        skills = []
        for req in job["profile"]["requirements"]:
            item = skills_by_name.get(req["skill"].lower(), {"skill":req["skill"],"evidence_level":0,"evidence":[],"self_reported":""})
            context = requirement_context.get(req['skill'].casefold(), {})
            skills.append({**item,"required_level":req["required_level"],"tier":skill_tier(item["evidence_level"],req["required_level"]),"hard":context.get('type', '硬性' if req['hard'] else '加分')=='硬性',"requirement_quote":req["quote"], 'requirement_context':context})
        dimensions = [d for d in obj["dimensions"] if d["dimension_id"] in {"D1","D3","D5"}]
        gpa = gpa_tier(redact(resume["text"]), rubric)
        dimensions.append(gpa or dimension_result('D2', 'insufficient', [], ['简历未见明确成绩或排名，奖学金不单独成档']))
        dimensions.append(d4_result(skills))
        for id in priorities["enabled"]:
            if not any(d["dimension_id"]==id for d in dimensions): dimensions.append(dimension_result(id, 'insufficient', [], ['当前文本缺少必要锚点证据']))
        dimensions = [d for d in dimensions if d["dimension_id"] in priorities["enabled"]]
        for d in dimensions:
            d.update({"name":rubric["dimensions"][d["dimension_id"]],"priority":priorities["priorities"][d["dimension_id"]]})
        visible = [resume['display_name'], job['title']]
        for d in dimensions:
            visible.extend([d['name'], rationale_for_display(d['rationale'], presentation, actor.startswith('candidate:'), job['title']), *d['evidence']])
        for skill in skills:
            visible.extend([skill['skill'], skill['requirement_quote'], *skill['evidence']])
        if any(presentation_violations(text, presentation, enterprise=actor.startswith('enterprise:')) for text in visible):
            self.db.audit('报告呈现阻断', {'reason': '结果文案或原文命中呈现禁词，不签发报告', 'job_id':job['id']}, actor, '告警')
            raise DomainError('PRESENTATION_BLOCKED', '结果加载中，请稍后重试', 422)
        questions = []
        for s in skills:
            if {'了解':1, '熟悉':2, '熟练':3, '精通':4}.get(s['self_reported'], 0)>s['evidence_level']:
                questions.append({"type":"简历自评高于描述","item":s["skill"],"hint":f"简历自评{s['self_reported']}；现有描述支持的行为较有限。面试可进一步了解具体职责与产出。","evidence":s["evidence"]})
            elif s["evidence_level"]==0 and s["hard"]:
                questions.append({"type":"关键项缺失","item":s["skill"],"hint":"简历未见该技能的使用描述。面试可了解实际使用场景。","evidence":[s["requirement_quote"]]})
            elif 0 < s['evidence_level'] < s['required_level']:
                questions.append({'type':'描述与要求的差距','item':s['skill'],'hint':'请结合实际任务，进一步了解职责、产出及需要培养的部分。','evidence':s['evidence']})
        for r in (brief or {}).get('requirements', []):
            if not r['assessable']:
                questions.append({'type':'需要沟通确认','item':r['content'],'hint':'用人方已说明此期待，简历不足以直接评估，可在面试中了解具体经历与工作安排。','evidence':[]})
        for d in dimensions:
            if d["tier"]=="insufficient": questions.append({"type":"关键项缺失","item":d["name"],"hint":"现有简历描述不足，面试可进一步了解相关经历。","evidence":[]})
        partial = lambda d: '部分证据不足' in d['rationale']
        structure = {"strengths":[d for d in dimensions if d["tier"] in {"B4","B5"} and not partial(d)],"weaknesses":[d for d in dimensions if d["tier"] in {"B1","B2","B3"} and not partial(d)],"insufficient":[d for d in dimensions if d["tier"]=="insufficient" or partial(d)]}
        return {"hiring_brief_snapshot":brief,"display_name":resume["display_name"],"job_title":job["title"],"dimensions":dimensions,"skill_levels":skills,"sort_key":sort_key(dimensions,priorities),"structure_view":structure,"open_questions":questions,"followups":[],"confidence":"low" if len(structure["insufficient"])>=2 else "high","status":"待确认","profile_version":job["version"],"profile_snapshot":job["profile"],"rubric_version":rubric["version"],"rubric_snapshot":rubric,"priority_version":priorities["version"],"priority_snapshot":priorities,"model_version":self.models.resolve("deepseek").model if self.models.enabled else "local-demo-rules-1.1","prompt_version":"evidence-rubric-v0.9.6-3" if self.models.enabled else "evidence-rubric-v0.9.6-1","mode":self.settings.llm_mode,"pack_version":self.config.pack()["pack_version"],"assessed_at":now()}

    def assess(self, data, actor, authorize=None):
        self.writable(); self.enterprise(actor)
        job = self.owned("job_profiles",data.job_id,actor)
        if job["status"] != "已确认": raise DomainError("PROFILE_UNCONFIRMED","请先确认岗位画像")
        if self.is_paused(job["id"],actor): raise DomainError("ASSESSMENT_PAUSED","连续整份打回已暂停自动分析，请检查标准后手动恢复",409)
        resumes = [self.active_resume(id,actor) for id in data.resume_ids]
        for resume in resumes: self.resume_job_scope(resume, job['id'])
        reports, errors = [], []
        for resume in resumes:
            try:
                payload = self.evaluate(job,resume,actor)
                with self.db.transaction() as cx:
                    cx.execute('BEGIN IMMEDIATE')
                    if authorize and not authorize():
                        raise DomainError('ENTERPRISE_VERIFICATION_REQUIRED', '招聘权限已暂停，不能保存新报告。', 403)
                    self.active_resume(resume['id'], actor, cx)
                    reports.append(self.db.insert("ability_reports",payload,actor,"synthetic" if "synthetic" in {job["data_origin"],resume["data_origin"]} else "real",cx=cx,job_id=job["id"],resume_id=resume["id"]))
            except DomainError as exc:
                errors.append({"resume_id":resume["id"],"name":resume["display_name"],"code":exc.code,"message":exc.message})
                self.db.audit("分析失败",errors[-1],actor,"告警")
                if exc.code=="COST_BUDGET": break
        return {"reports":reports,"errors":errors}

    def is_paused(self, job_id, actor):
        events = [a for a in self.db.list("audit_logs",owner=actor) if a["event_type"] in {"分析暂停","分析恢复"} and a["detail"].get("job_id")==job_id]
        return bool(events and events[0]["event_type"]=="分析暂停")

    def review(self, data, actor):
        self.writable(); self.enterprise(actor)
        with self.db.transaction() as cx:
            report = self.db.get("ability_reports",data.report_id,cx)
            if not report or report["owner"]!=actor: raise DomainError("NOT_FOUND","报告不可访问",404)
            if not self.material_visible(report, cx): raise DomainError('RESUME_CONSENT_UNAVAILABLE', '简历授权已结束，不能继续审阅。', 403)
            if report["status"]=="已打回": raise DomainError("REASSESS_REQUIRED","报告已打回，请重新分析后再审阅",409)
            before = None
            patch = {}
            if data.action == "单维改档":
                if report["status"]=="已确认": raise DomainError("REPORT_LOCKED","报告已确认，请先打回再重新分析",409)
                dim = next((d for d in report["dimensions"] if d["dimension_id"]==data.dimension_id),None)
                if not dim or not data.tier_after: raise DomainError("REVIEW_DIMENSION","请选择有效维度与新的关系")
                if data.tier_after!="insufficient" and not dim["evidence"]: raise DomainError("EVIDENCE_REQUIRED","没有原文依据的维度不能改为明确关系",422)
                before = dim["tier"]
                dim.update({**dimension_result(data.dimension_id, data.tier_after, dim['evidence'], ['人工审阅说明：' + data.reason]), 'review_reason':data.reason})
                patch = {"dimensions":report["dimensions"],"sort_key":sort_key(report["dimensions"],report["priority_snapshot"])}
                patch["structure_view"] = {"strengths":[d for d in report["dimensions"] if d["tier"] in {"B4","B5"}],"weaknesses":[d for d in report["dimensions"] if d["tier"] in {"B1","B2","B3"}],"insufficient":[d for d in report["dimensions"] if d["tier"]=="insufficient"]}
            elif data.action == "确认":
                if report["status"]=="已确认": raise DomainError("REPORT_LOCKED","报告已确认",409)
                patch = {"status":"已确认","confirmed_at":now()}
            else: patch = {"status":"已打回"}
            event = self.db.insert("review_events",{**data.model_dump(exclude={"report_id"}),"tier_before":before},actor,report["data_origin"],cx=cx,report_id=report["id"])
            if data.action in {"单维改档","整份打回"}:
                self.db.insert("calibration_memory",{"dimension_id":data.dimension_id,"pattern":redact(data.reason),"confirmed":False,"deleted_at":None},actor,report["data_origin"],cx=cx,job_id=report["job_id"],source_event_id=event["id"])
            result = self.db.update("ability_reports",report["id"],patch,cx)
            self.db.audit("报告审阅",{"report_id":report["id"],"job_id":report["job_id"],"action":data.action},actor,cx=cx)
        events = [a for a in self.db.list("audit_logs",owner=actor) if a["event_type"]=="报告审阅" and a["detail"].get("job_id")==report["job_id"]][:3]
        if len(events)==3 and all(a["detail"]["action"]=="整份打回" for a in events): self.db.audit("分析暂停",{"job_id":report["job_id"],"reason":"连续三份整份打回"},actor,"告警")
        return result

    def followups(self, id, actor):
        self.writable()
        report = self.owned("ability_reports",id,actor)
        if report["status"]!="已确认": raise DomainError("REPORT_UNCONFIRMED","确认报告后才可生成追问")
        items = [{"item":q["item"],"gap_evidence":q["evidence"],"question":f"请结合一个具体经历，介绍{q['item']}相关的任务、个人职责、关键选择与结果。"} for q in report["open_questions"]]
        return self.db.update("ability_reports",id,{"followups":items})

    def ranking(self, job_id, actor):
        self.enterprise(actor); self.owned("job_profiles",job_id,actor)
        reports = self.visible_material_records("ability_reports",actor,job_id=job_id)
        latest = {}
        for report in reports: latest.setdefault(report["resume_id"], report)
        reports = [r for r in latest.values() if r["status"]=="已确认"]
        reports.sort(key=lambda r:key_tuple(r["sort_key"]),reverse=True)
        previous, rank = None, 0
        for index, r in enumerate(reports):
            key = key_tuple(r["sort_key"])
            if key != previous: rank = index+1
            r["rank"],previous = rank,key
        return reports

    def batch(self, job_id, actor):
        self.writable(); self.enterprise(actor)
        job = self.owned("job_profiles",job_id,actor)
        if job["status"]!="已确认": raise DomainError("PROFILE_UNCONFIRMED","请先确认岗位画像")
        resumes = [r for r in self.active_resumes(actor) if not r.get('source_application_id') or r.get('application_job_id') == job_id]
        if self.settings.vector:
            ids = self.retrieval.search(job["source_jd"],actor,self.settings.env,job["data_origin"])
            positions = {id:i for i,id in enumerate(dict.fromkeys(ids))}
            resumes.sort(key=lambda r:positions.get(r["id"],len(positions)))
            self.db.audit("检索上下文",{"job_id":job_id,"retrieved_resumes":len(positions),"screened_resumes":len(resumes),"all_resumes_retained":True},actor)
        results = []
        for r in resumes:
            from .deterministic import evidence_skills
            names = list(dict.fromkeys(req['skill'] for req in job['profile']['requirements']))
            known = {s["skill"].lower():s for s in evidence_skills(redact(r["text"]), names)}
            hits, misses = [], []
            for req in job["profile"]["requirements"]:
                item = known.get(req["skill"].lower())
                entry = {"skill":req["skill"],"requirement_quote":req["quote"],"evidence":item["evidence"] if item else [],"reason":"描述支持要求" if item and item["evidence_level"]>=req["required_level"] else "现有描述与要求有差距或证据不足"}
                (hits if item and item["evidence_level"]>=req["required_level"] else misses).append(entry)
            rules = []
            degrees = ["大专","本科","硕士","博士"]
            need = job["profile"].get("education")
            actual = next((v for v in reversed(degrees) if v in r["text"]),None)
            if need and actual and degrees.index(actual)<degrees.index(need): rules.append("R-EDU-01")
            tier = "存疑" if rules else "高匹配" if hits and not misses else "潜力"
            gate = "规则未通过" if rules else "信息待补充" if need and not actual else "通过"
            results.append(self.db.insert("batches",{"display_name":r["display_name"],"tier":tier,"hits":hits,"misses":misses,"hard_gate_result":gate,"hard_gate_rule_ids":rules,"tier_reason":"规则只标记，不删除；技能依据可逐项展开","profile_version":job["version"]},actor,r["data_origin"],job_id=job_id,resume_id=r["id"]))
        return results

    def clarify(self, job_id, actor):
        self.enterprise(actor); self.owned("job_profiles",job_id,actor)
        return {"questions":QUESTIONS,"generator":"structured-questions-1.0"}

    def current_brief(self, job):
        if not job.get('owner') or not job.get('id'): return None
        return next((b for b in self.db.list('hiring_briefs', owner=job['owner'], job_id=job['id'])
                     if b['profile_version'] == job['version']), None)

    def brief(self, data, actor):
        self.writable(); self.enterprise(actor)
        job = self.owned("job_profiles",data.job_id,actor)
        if set(data.answers)-{q["id"] for q in QUESTIONS}: raise DomainError("ANSWER_INVALID","问答包含未知问题")
        for q in QUESTIONS:
            if data.answers.get(q["id"]) and data.answers[q["id"]] not in q["options"]: raise DomainError("ANSWER_INVALID","请使用提供的澄清选项")
        source = data.answers.get("source","不清楚 / 跳过")
        unresolved = source=="不清楚 / 跳过"
        overrides = {r.skill.strip().casefold():r for r in data.requirement_overrides}
        names = {r['skill'].casefold() for r in job['profile']['requirements']}
        if len(overrides)!=len(data.requirement_overrides) or set(overrides)-names:
            raise DomainError('REQUIREMENT_INVALID', '逐项澄清只能关联当前画像中的唯一技能。', 422)
        trainable = data.answers.get('trainable')=='技术细节' and source!='合规或硬性制度'
        essential = data.answers.get('essential')=='核心技术栈'
        requirements = []
        for r in job['profile']['requirements']:
            override = overrides.get(r['skill'].casefold())
            kind = override.type if override else '可培养' if trainable else '硬性' if r['hard'] else '加分'
            priority = override.priority if override else 'P2' if kind=='可培养' else 'P0' if not unresolved and essential and r['hard'] else 'P1'
            requirements.append({'content':r['skill'],'type':kind,'source_tag':'未澄清' if unresolved else source,'assessable':True,
                'priority':priority,'origin':'JD原文','jd_quote':r['quote'], 'basis':'逐项确认' if override else '澄清回答',
                'business_purpose':data.answers.get('purpose','不清楚 / 跳过'),'success_standard':data.answers.get('success','不清楚 / 跳过')})
        for key, label in [('purpose','业务目的'),('success','成功标准'),('essential','不可妥协的方面'),('trainable','可培养的方面')]:
            answer = data.answers.get(key, '不清楚 / 跳过')
            if answer == '不清楚 / 跳过' or (key=='essential' and essential): continue
            requirements.append({'content':label+'：'+answer,'type':'可培养' if key=='trainable' else '业务期待','source_tag':'企业澄清',
                'assessable':False,'priority':'P2' if key=='trainable' else 'P0','origin':'澄清回答','jd_quote':'',
                'coverage_reason':'需要具体经历或双方沟通确认，不能只凭技能名称判断。'})
        return self.db.insert("hiring_briefs",{"requirements":requirements,"clarification_qa":data.answers,"unclarified_count":len(requirements) if unresolved else 0,"profile_version":job["version"],"version":now()},actor,job["data_origin"],job_id=job["id"])

    def diagnose(self, job, actor):
        findings = []
        text = job["source_jd"]
        year = re.search(r"[3-9一二三四五六七八九]+\s*年(?:以上)?(?:工作|相关|开发)?经验",text)
        campus = re.search(r"应届|校招",text)
        if year and campus: findings.append({"type":"内部矛盾","jd_quote":campus[0]+" / "+year[0],"statement":"届别与工作经验年限要求可能存在矛盾，请确认适用对象。"})
        for m in re.finditer(r"有责任心|责任心强|抗压能力强|性格开朗",text): findings.append({"type":"不具备可评性","jd_quote":m[0],"statement":"该要求难以仅凭简历文字判断，适合在实际沟通中了解。"})
        benchmarks = self.valid_benchmarks(job)
        for req in job["profile"]["requirements"]:
            ref = next((b for b in benchmarks if b["skill"]==req["skill"] and b["sample_size"]>=20 and b["rubric_version"]==self.config.get("rubric")["version"]),None)
            if ref and req["required_level"]>ref["upper_level"]:
                findings.append({"type":"超出同级基准","jd_quote":req["quote"],"statement":f"要求高于同类岗位常见要求 {req['required_level']-ref['upper_level']} 级。","benchmark_ref":ref["id"],"source_label":ref["source_type"]})
        return {"findings":findings,"finding_count":len(findings),"benchmark_available":bool(benchmarks),"profile_version":job["version"],"rubric_version":self.config.get("rubric")["version"]}

    def fit(self, data, actor):
        self.writable(); self.candidate(actor)
        resume = self.active_resume(data.resume_id,actor)
        if data.jd:
            if data.manual_profile:
                profile=data.manual_profile.model_dump()
                if not profile['requirements'] or any(r['quote'] not in data.jd for r in profile['requirements']):
                    raise DomainError('EVIDENCE_INVALID','手工画像至少需要一项技能，且每条引用必须来自目标 JD 原文。',422)
            else:
                try: profile=self.gateway.jd(redact(data.jd))
                except DomainError as exc:
                    if exc.code!='AGENT_FAILED': raise
                    raise DomainError('JD_PARSE_FAILED','岗位解析失败，可使用手工确认画像后继续对照。',502) from None
            job=self.db.insert("job_profiles",{"title":data.title,"source_jd":data.jd,"profile":profile,"version":1,"status":"已确认","source_type":"user_paste","history":[],"mode":self.settings.llm_mode},actor,resume["data_origin"])
        else:
            if data.manual_profile: raise DomainError('FIT_TARGET','手工画像仅适用于本人粘贴的目标 JD。',422)
            job = self.db.get("job_profiles",data.job_id)
            if job and not self.job_visible(job,actor): raise DomainError("NOT_FOUND","目标岗位不可访问",404)
        if not job or job["status"]!="已确认": raise DomainError("NOT_FOUND","公开岗位不存在或尚未确认",404)
        payload = self.evaluate(job,resume,actor)
        payload['fit_summary'] = fit_summary(payload['dimensions'], payload['skill_levels'])
        payload.pop("open_questions")
        payload["diagnosis"] = self.diagnose(job,actor)
        payload["gap_explanations"] = [{"skill":s["skill"],"requirement":payload["rubric_snapshot"]["skill_anchors"][str(s["required_level"])] ,"evidence_anchor":payload["rubric_snapshot"]["skill_anchors"][str(s["evidence_level"])],"evidence":s["evidence"]} for s in payload["skill_levels"] if s["tier"] not in {"B4","B5"}]
        return self.db.insert("fit_reports",payload,actor,"synthetic" if "synthetic" in {job["data_origin"],resume["data_origin"]} else "real",job_id=job["id"],resume_id=resume["id"])

    def compare(self, data, actor):
        self.writable(); self.candidate(actor)
        resume = self.active_resume(data.resume_id,actor)
        results, errors = [], []
        targets = targets_for(self, data, actor)
        for target in targets:
            try:
                results.append(evaluate_target(self, target, resume, actor))
            except DomainError as exc:
                errors.append({'job_ref': target['job_ref'], 'error': exc.message, 'code': exc.code})
        return self.db.insert("job_comparison_runs",{"job_texts":[{"text":t,"pasted_at":now()} for t in data.job_texts],
            'job_ids': data.job_ids, 'resume_name': resume['display_name'], 'status': 'completed' if not errors else 'partial' if results else 'failed',
            'processed':len(targets), 'total':len(targets), 'message':'岗位契合度分析已完成。', 'ranked_results':rank_results(results), 'errors':errors,
            "rubric_version":self.config.get("rubric")["version"], 'policy_version': FIT_POLICY},actor,resume["data_origin"],resume_id=resume["id"])

    def valid_benchmarks(self, job):
        # Aggregates produced before distinct-job sampling cannot be trusted.
        rows = self.db.list('role_benchmarks',owner=job['owner'],job_id=job['id'])
        unique = {}
        for row in rows:
            ids = row.get('sample_job_ids',[])
            if (row.get('sampling_method') != 'distinct-job-v1' or row['sample_size'] < 20
                or len(set(ids)) != row['sample_size']
                or row['rubric_version'] != self.config.get('rubric')['version']): continue
            unique.setdefault(row['skill'].strip().casefold(),row)
        return list(unique.values())

    def build_benchmark(self, job_id, actor):
        self.writable(); self.enterprise(actor)
        job = self.owned("job_profiles",job_id,actor)
        pool = [j for j in self.db.list("job_profiles",owner=actor) if j["status"]=="已确认" and j["profile"]["direction"]==job["profile"]["direction"] and j["data_origin"]==job["data_origin"]]
        created = []
        unique = {r['skill'].strip().casefold():r for r in job['profile']['requirements']}
        for name, req in unique.items():
            # Legacy profiles may contain duplicates. A job contributes at most once.
            samples = [j for j in pool if any(r['skill'].strip().casefold()==name for r in j['profile']['requirements'])]
            levels = [max(r['required_level'] for r in j['profile']['requirements'] if r['skill'].strip().casefold()==name) for j in samples]
            if len(levels)<20: continue
            created.append(self.db.insert("role_benchmarks",{"skill":req["skill"],"sample_size":len(levels),"sampling_method":"distinct-job-v1","sample_job_ids":[j['id'] for j in samples],"distribution":dict(Counter(map(str,levels))),"lower_level":min(levels),"upper_level":max(levels),"source_type":"B_synthetic" if job["data_origin"]=="synthetic" else "A_derived","rubric_version":self.config.get("rubric")["version"]},actor,job["data_origin"],job_id=job_id))
        return {"records":created,"message":"基准已生成" if created else "同类岗位样本不足，暂不生成基准"}

    def quality_summary(self, job_id, actor):
        self.enterprise(actor);self.owned('job_profiles',job_id,actor)
        reports=self.visible_material_records('ability_reports',actor,job_id=job_id)
        latest={}
        for row in reports: latest.setdefault(row['resume_id'],row)
        latest={key:r for key,r in latest.items() if r['status']!='已打回'}
        report_ids={r['id'] for r in latest.values()}
        events=[r for r in self.db.list('review_events',owner=actor) if r['report_id'] in {r['id'] for r in reports}]
        changed={e['report_id'] for e in events if e['action']=='单维改档'}
        labels=self.config.get('presentation')['tier_labels']; dimensions={};insufficient=0;observations=0
        for report in latest.values():
            for d in report['dimensions']:
                summary=dimensions.setdefault(d['dimension_id'],{'name':d['name'],'distribution':{},'count':0,'insufficient_count':0})
                label=labels.get(d['tier'],'证据不足');summary['distribution'][label]=summary['distribution'].get(label,0)+1;summary['count']+=1
                unknown=d['tier']=='insufficient' or '部分证据不足' in d.get('rationale','')
                summary['insufficient_count']+=int(unknown);insufficient+=int(unknown);observations+=1
        daily={}
        for report in reports:
            day=report['created_at'][:10];bucket=daily.setdefault(day,{'date':day,'generated':0,'changed':0});bucket['generated']+=1
        for event in events:
            if event['action']=='单维改档':
                day=event['created_at'][:10];daily.setdefault(day,{'date':day,'generated':0,'changed':0})['changed']+=1
        batches={}
        for row in self.visible_material_records('batches',actor,job_id=job_id): batches.setdefault(row['resume_id'],row)
        return {'reports_total':len(latest),'historical_reports':len(reports),'batch_resumes':len(batches),
            'insufficient_rate':insufficient/observations if observations else None,'dimension_observations':observations,
            'manually_changed_reports':len(changed & report_ids),'human_change_rate':len(changed & report_ids)/len(latest) if latest else None,
            'dimensions':list(dimensions.values()),'trend':sorted(daily.values(),key=lambda r:r['date'])[-30:],
            'scope':'每份简历的最新非打回报告；趋势为最近 30 个有记录的日期，修改数按人工修改事件计。',
            'note':'此处统计材料与审阅记录，不代表模型准确率、人工校准通过或人员录用判断。'}

    def purge(self, env, actor):
        self.enterprise(actor)
        if env not in {"demo","dev"} or env!=self.settings.env: raise DomainError("PURGE_ENV","必须显式指定当前非生产环境")
        self.maintenance=True
        try:
            with self.db.transaction() as cx:
                import sqlite3
                backup = self.settings.data_dir / "backups" / (now().replace(":","-")+".sqlite3")
                backup.parent.mkdir(exist_ok=True)
                with sqlite3.connect(backup) as dst: cx.backup(dst)
                selected = {table:[row["id"] for row in cx.execute(f"SELECT id FROM {table} WHERE env=? AND data_origin='synthetic'",(env,))] for table in TABLES if table!="audit_logs"}
                # Reject instead of cascading deletion into any real record.
                for table, refs in TABLES.items():
                    for key,target in refs.items():
                        for id in selected.get(target,[]):
                            if cx.execute(f"SELECT 1 FROM {table} WHERE {key}=? AND data_origin='real'",(id,)).fetchone(): raise DomainError("REAL_DEPENDENCY","真实记录引用了合成记录；为保护真实数据，清理已拒绝",409)
                self.retrieval.remove(selected["resumes"])
                order = ["applications","ai_sessions","match_results","job_comparison_runs","fit_reports","calibration_memory","review_events","ability_reports","batches","jd_diagnoses","hiring_briefs","role_benchmarks","preference_submissions","resumes","candidates","job_profiles"]
                for table in order: cx.execute(f"DELETE FROM {table} WHERE env=? AND data_origin='synthetic'",(env,))
                cx.execute("DELETE FROM role_benchmarks WHERE env=?",(env,))  # invalidated aggregates need explicit rebuild
                if cx.execute("PRAGMA foreign_key_check").fetchall(): raise DomainError("ORPHAN_CHECK","引用检查失败，已回滚",500)
                self.db.audit("数据清理",{"counts":{k:len(v) for k,v in selected.items()},"env":env,"backup":backup.name,"aggregates":"已失效，需重新生成"},actor,cx=cx)
            raw = self.settings.data_dir / "raw_files"
            for cid in selected["candidates"]:
                (raw / (cid+".txt")).unlink(missing_ok=True)
            return {"counts":{k:len(v) for k,v in selected.items()},"backup":backup.name}
        finally:
            self.maintenance=False

    def csv_export(self, reports):
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        presentation = self.config.get('presentation')
        writer.writerow([presentation['bias_notice']])
        writer.writerow(["位次","脱敏名","岗位","相对要求关系","证据不足项"])
        labels = self.config.get("presentation")["tier_labels"]
        def safe(value):
            value=str(value)
            return "'"+value if value.lstrip().startswith(("=","+","-","@")) else value
        for r in reports:
            row = [r["rank"],safe(r["display_name"]),safe(r["job_title"]),"；".join(d["name"]+"："+labels[d["tier"]] for d in r["dimensions"]),"、".join(d["name"] for d in r["dimensions"] if d["tier"]=="insufficient")]
            if any(presentation_violations(value, presentation) for value in row):
                self.db.audit('导出呈现阻断', {'report_id':r.get('id'), 'reason':'导出含呈现禁词'}, r.get('owner','enterprise:demo'), '告警')
                raise DomainError('PRESENTATION_BLOCKED', '结果加载中，请稍后重试', 422)
            writer.writerow(row)
        writer.writerow([presentation['footer']])
        return stream.getvalue()
