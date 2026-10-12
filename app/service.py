import csv
import hashlib
import io
import json
import re
from collections import Counter
from pathlib import Path
from .agents import AgentGateway
from .configuration import Configuration
from .db import Database, TABLES, now
from .deterministic import gpa_tier, skill_tier, d4_result, dimension_result, sort_key, key_tuple, match_preferences, mentions, presentation_violations, rationale_for_display
from .errors import DomainError
from .models import JobProfile
from .retrieval import LocalRetrieval
from .security import redact

QUESTIONS = [
 {"id":"purpose","question":"这次招聘主要解决什么问题？","options":["补充团队能力","支持新业务","人员补充","不清楚 / 跳过"]},
 {"id":"success","question":"半年后，最希望看到什么成果？","options":["独立负责交付","改善产品或性能","支撑团队协作","不清楚 / 跳过"]},
 {"id":"essential","question":"哪些要求源于当前业务需要？","options":["核心技术栈","相关项目经历","相关实践经历","不清楚 / 跳过"]},
 {"id":"trainable","question":"哪些方面可以在入职后继续培养？","options":["技术细节","业务知识","协作方式","不清楚 / 跳过"]},
 {"id":"source","question":"这些要求主要来自哪里？","options":["团队能力缺口","业务需要","合规或硬性制度","模板惯性","不清楚 / 跳过"]}
]


class TalentService:
    def __init__(self, settings):
        self.settings = settings
        self.db = Database(settings)
        self.config = Configuration(settings.data_dir)
        self.gateway = AgentGateway(settings, self.record_call)
        self.retrieval = LocalRetrieval(settings)
        self.maintenance = False

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
        return obj

    def writable(self):
        if self.maintenance:
            raise DomainError("MAINTENANCE", "数据维护中，请稍后再试", 503)
        if self.settings.env == "prod":
            raise DomainError("PRODUCTION_DISABLED", "此版本为演示原型，请先完善身份认证与授权机制后再启用生产写入", 403)

    def budget_check(self):
        spent = sum(a["detail"].get("cost_cny",0) for a in self.db.list("audit_logs") if a["event_type"] == "Agent 调用")
        if spent >= self.settings.budget:
            raise DomainError("COST_BUDGET", "当前环境 AI 成本预算已用完，请调整预算或改用演示模式", 429)

    def record_call(self, detail):
        self.db.audit("Agent 调用", detail, result=detail.pop("result", "正常"))

    def create_job(self, data, actor):
        self.writable(); self.enterprise(actor); self.budget_check()
        profile = JobProfile.model_validate(data.manual_profile).model_dump() if data.manual_profile else self.gateway.jd(redact(data.jd))
        if any(r["quote"] not in data.jd for r in profile["requirements"]): raise DomainError("EVIDENCE_INVALID","要求必须引用 JD 原文")
        job = self.db.insert("job_profiles", {"title":data.title,"source_jd":data.jd,"profile":profile,"version":1,"status":"待确认","history":[],"mode":self.settings.llm_mode},actor,data.data_origin)
        self.db.audit("岗位创建", {"job_id":job["id"],"profile_version":1},actor)
        return job

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

    def create_resume(self, data, actor):
        self.writable()
        safe = redact(data.text)
        if len(safe.strip()) < 10: raise DomainError("NO_USABLE_TEXT", "剥离个人信息后没有足够的简历内容",422)
        if self.settings.vector: self.retrieval.initialize()
        candidate = self.db.insert("candidates", {"display_name":data.name},actor,data.data_origin)
        folder = self.settings.data_dir / "raw_files"
        folder.mkdir(exist_ok=True)
        raw_path = folder / (candidate["id"] + ".txt")
        raw_path.write_text(data.text,encoding="utf-8")
        resume = self.db.insert("resumes", {"display_name":data.name,"text":safe,"raw_file_path":str(raw_path),"parse_status":"成功","source_hash":hashlib.sha256(data.text.encode()).hexdigest()},actor,data.data_origin,candidate_id=candidate["id"])
        try:
            self.retrieval.upsert(resume)
        except Exception as exc:
            self.db.audit("向量索引失败",{"resume_id":resume["id"],"error_type":type(exc).__name__},actor,"告警")
        self.db.audit("简历导入",{"resume_id":resume["id"],"data_origin":data.data_origin},actor)
        return self.public_resume(resume)

    def public_resume(self, resume):
        return {k:v for k,v in resume.items() if k not in {"raw_file_path","source_hash"}}

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
            obj = self.owned("resumes",data.resume_id,actor)
        cfg = self.config.get("preferences")
        if data.dimension_version != cfg["version"]: raise DomainError("DIMENSION_VERSION_MISMATCH","维度口径已更新，请刷新后重新填写")
        dims = {d["id"]:d for d in cfg["dimensions"]}
        if set(data.dimensions) - set(dims): raise DomainError("UNKNOWN_DIMENSION", "填报包含未知维度")
        for id, d in dims.items():
            if d["required"] and id not in data.dimensions: raise DomainError("REQUIRED_DIMENSION", "请完成三项必填偏好；允许选择无法判断")
            value = data.dimensions.get(id)
            if value is not None and value not in d["options"]: raise DomainError("INVALID_OPTION", "偏好必须使用当前维度表提供的选项")
        if not data.share_with_counterparty: raise DomainError("SHARING_REQUIRED", "请确认将偏好用于双方对照并向该次对照的另一方展示依据")
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
        if not job or not resume or actor not in {job["owner"],resume["owner"]}: raise DomainError("NOT_FOUND","无法访问此次对照",404)
        if job["status"] != "已确认": raise DomainError("PROFILE_UNCONFIRMED","请先确认岗位画像")
        ent = self.latest_preference("enterprise",job["id"])
        cand = self.latest_preference("candidate",resume["id"])
        if not ent or not cand: raise DomainError("PREFERENCE_MISSING","请双方先完成偏好填报")
        if not ent["share_with_counterparty"] or not cand["share_with_counterparty"]: raise DomainError("SHARING_REQUIRED","双方尚未同意共享对照依据",403)
        result = match_preferences(ent,cand,self.config.get("preferences"))
        result.update({"rubric_version":self.config.get("rubric")["version"],"job_title":job["title"],"candidate_name":resume["display_name"],"enterprise_owner":job["owner"],"candidate_owner":resume["owner"],"ambience_text":ent["ambience_text"],"ent_snapshot":ent["dimensions"],"cand_snapshot":cand["dimensions"]})
        existing = next((m for m in self.db.list("match_results",job_id=job["id"],resume_id=resume["id"]) if m["ent_submission_id"]==ent["id"] and m["cand_submission_id"]==cand["id"] and m["engine_version"]==result["engine_version"]),None)
        if existing: return existing
        origin = "synthetic" if "synthetic" in {job["data_origin"],resume["data_origin"]} else "real"
        row = self.db.insert("match_results",result,job["owner"],origin,job_id=job["id"],resume_id=resume["id"],ent_submission_id=ent["id"],cand_submission_id=cand["id"])
        self.db.audit("偏好对照",{"match_id":row["id"],"engine_version":result["engine_version"]},actor)
        return row

    def visible_matches(self, actor):
        rows = [m for m in self.db.list("match_results") if actor in {m["enterprise_owner"],m["candidate_owner"]}]
        for row in rows:
            a = self.latest_preference("enterprise",row["job_id"])
            b = self.latest_preference("candidate",row["resume_id"])
            row["outdated"] = not a or not b or a["id"] != row["ent_submission_id"] or b["id"] != row["cand_submission_id"] or row["dimension_version"]!=self.config.get("preferences")["version"]
        return rows

    def evaluate(self, job, resume, actor):
        self.budget_check()
        rubric, priorities = self.config.get("rubric"), self.config.get("priorities")
        presentation = self.config.get('presentation')
        if any(any(term not in presentation.get(key, '') for term in ('可能存在偏差', '系统不设合格线')) for key in ('bias_notice', 'footer')):
            self.db.audit('报告呈现阻断', {'reason': '首屏或页脚偏差提示不完整'}, actor, '告警')
            raise DomainError('NOTICE_REQUIRED', '报告生成未完成，请重试', 422)
        memory = [redact(m["pattern"]) for m in self.db.list("calibration_memory",owner=actor,job_id=job["id"]) if m["confirmed"] and not m.get("deleted_at")]
        obj = self.gateway.evaluate(redact(resume["text"]),job["profile"],rubric,memory,major_map=self.config.get('major-map'))
        skills_by_name = {s["skill"].lower():s for s in obj["skills"]}
        skills = []
        for req in job["profile"]["requirements"]:
            item = skills_by_name.get(req["skill"].lower(), {"skill":req["skill"],"evidence_level":0,"evidence":[],"self_reported":""})
            skills.append({**item,"required_level":req["required_level"],"tier":skill_tier(item["evidence_level"],req["required_level"]),"hard":req["hard"],"requirement_quote":req["quote"]})
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
        for d in dimensions:
            if d["tier"]=="insufficient": questions.append({"type":"关键项缺失","item":d["name"],"hint":"现有简历描述不足，面试可进一步了解相关经历。","evidence":[]})
        partial = lambda d: '部分证据不足' in d['rationale']
        structure = {"strengths":[d for d in dimensions if d["tier"] in {"B4","B5"} and not partial(d)],"weaknesses":[d for d in dimensions if d["tier"] in {"B1","B2","B3"} and not partial(d)],"insufficient":[d for d in dimensions if d["tier"]=="insufficient" or partial(d)]}
        return {"display_name":resume["display_name"],"job_title":job["title"],"dimensions":dimensions,"skill_levels":skills,"sort_key":sort_key(dimensions,priorities),"structure_view":structure,"open_questions":questions,"followups":[],"confidence":"low" if len(structure["insufficient"])>=2 else "high","status":"待确认","profile_version":job["version"],"profile_snapshot":job["profile"],"rubric_version":rubric["version"],"rubric_snapshot":rubric,"priority_version":priorities["version"],"priority_snapshot":priorities,"model_version":self.settings.model if self.settings.llm_mode=="deepseek" else "local-demo-rules-1.1","prompt_version":"evidence-rubric-v0.9.6-1","mode":self.settings.llm_mode,"pack_version":self.config.pack()["pack_version"],"assessed_at":now()}

    def assess(self, data, actor):
        self.writable(); self.enterprise(actor)
        job = self.owned("job_profiles",data.job_id,actor)
        if job["status"] != "已确认": raise DomainError("PROFILE_UNCONFIRMED","请先确认岗位画像")
        if self.is_paused(job["id"],actor): raise DomainError("ASSESSMENT_PAUSED","连续整份打回已暂停自动分析，请检查标准后手动恢复",409)
        resumes = [self.owned("resumes",id,actor) for id in data.resume_ids]
        reports, errors = [], []
        for resume in resumes:
            try:
                payload = self.evaluate(job,resume,actor)
                reports.append(self.db.insert("ability_reports",payload,actor,"synthetic" if "synthetic" in {job["data_origin"],resume["data_origin"]} else "real",job_id=job["id"],resume_id=resume["id"]))
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
        reports = self.db.list("ability_reports",owner=actor,job_id=job_id)
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
        resumes = self.db.list("resumes",owner=actor)
        if self.settings.vector:
            ids = self.retrieval.search(job["source_jd"],actor,self.settings.env,job["data_origin"])
            positions = {id:i for i,id in enumerate(dict.fromkeys(ids))}
            resumes.sort(key=lambda r:positions.get(r["id"],len(positions)))
            self.db.audit("检索上下文",{"job_id":job_id,"retrieved_resumes":len(positions),"screened_resumes":len(resumes),"all_resumes_retained":True},actor)
        results = []
        for r in resumes:
            from .deterministic import evidence_skills
            known = {s["skill"].lower():s for s in evidence_skills(r["text"])}
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

    def brief(self, data, actor):
        self.writable(); self.enterprise(actor)
        job = self.owned("job_profiles",data.job_id,actor)
        if set(data.answers)-{q["id"] for q in QUESTIONS}: raise DomainError("ANSWER_INVALID","问答包含未知问题")
        for q in QUESTIONS:
            if data.answers.get(q["id"]) and data.answers[q["id"]] not in q["options"]: raise DomainError("ANSWER_INVALID","请使用提供的澄清选项")
        source = data.answers.get("source","不清楚 / 跳过")
        unresolved = source=="不清楚 / 跳过"
        requirements = [{"content":r["skill"],"type":"硬性" if r["hard"] else "加分","source_tag":"未澄清" if unresolved else source,"assessable":True,"priority":"P1" if unresolved or not r["hard"] else "P0","origin":"JD原文","jd_quote":r["quote"]} for r in job["profile"]["requirements"]]
        return self.db.insert("hiring_briefs",{"requirements":requirements,"clarification_qa":data.answers,"unclarified_count":len(requirements) if unresolved else 0,"profile_version":job["version"],"version":now()},actor,job["data_origin"],job_id=job["id"])

    def diagnose(self, job, actor):
        findings = []
        text = job["source_jd"]
        year = re.search(r"[3-9一二三四五六七八九]+\s*年(?:以上)?(?:工作|相关|开发)?经验",text)
        campus = re.search(r"应届|校招",text)
        if year and campus: findings.append({"type":"内部矛盾","jd_quote":campus[0]+" / "+year[0],"statement":"届别与工作经验年限要求可能存在矛盾，请确认适用对象。"})
        for m in re.finditer(r"有责任心|责任心强|抗压能力强|性格开朗",text): findings.append({"type":"不具备可评性","jd_quote":m[0],"statement":"该要求难以仅凭简历文字判断，适合在实际沟通中了解。"})
        benchmarks = self.db.list("role_benchmarks",owner=job["owner"],job_id=job["id"])
        for req in job["profile"]["requirements"]:
            ref = next((b for b in benchmarks if b["skill"]==req["skill"] and b["sample_size"]>=20 and b["rubric_version"]==self.config.get("rubric")["version"]),None)
            if ref and req["required_level"]>ref["upper_level"]:
                findings.append({"type":"超出同级基准","jd_quote":req["quote"],"statement":f"要求高于同类岗位常见要求 {req['required_level']-ref['upper_level']} 级。","benchmark_ref":ref["id"],"source_label":ref["source_type"]})
        return {"findings":findings,"finding_count":len(findings),"benchmark_available":bool(benchmarks),"profile_version":job["version"],"rubric_version":self.config.get("rubric")["version"]}

    def fit(self, data, actor):
        self.writable(); self.candidate(actor)
        resume = self.owned("resumes",data.resume_id,actor)
        if data.jd:
            profile=self.gateway.jd(redact(data.jd))
            job=self.db.insert("job_profiles",{"title":data.title,"source_jd":data.jd,"profile":profile,"version":1,"status":"已确认","source_type":"user_paste","history":[],"mode":self.settings.llm_mode},actor,resume["data_origin"])
        else:
            job = self.db.get("job_profiles",data.job_id)
            if job and job["owner"].startswith("candidate:") and job["owner"]!=actor: raise DomainError("NOT_FOUND","目标岗位不可访问",404)
        if not job or job["status"]!="已确认": raise DomainError("NOT_FOUND","公开岗位不存在或尚未确认",404)
        payload = self.evaluate(job,resume,actor)
        payload.pop("open_questions")
        payload["diagnosis"] = self.diagnose(job,actor)
        payload["gap_explanations"] = [{"skill":s["skill"],"requirement":payload["rubric_snapshot"]["skill_anchors"][str(s["required_level"])] ,"evidence_anchor":payload["rubric_snapshot"]["skill_anchors"][str(s["evidence_level"])],"evidence":s["evidence"]} for s in payload["skill_levels"] if s["tier"] not in {"B4","B5"}]
        return self.db.insert("fit_reports",payload,actor,"synthetic" if "synthetic" in {job["data_origin"],resume["data_origin"]} else "real",job_id=job["id"],resume_id=resume["id"])

    def compare(self, data, actor):
        self.writable(); self.candidate(actor)
        resume = self.owned("resumes",data.resume_id,actor)
        results = []
        for index, text in enumerate(data.job_texts):
            try:
                profile = self.gateway.jd(redact(text))
                fake = {"id":"user-paste","title":text.splitlines()[0][:60] or f"岗位 {index+1}","profile":profile,"version":1}
                payload = self.evaluate(fake,resume,actor)
                results.append({"job_ref":index+1,"job_title":fake["title"],"dimensions":payload["dimensions"],"sort_key":payload["sort_key"],"basis_statement":"按相符及以上的维度数量、维度优先顺序与证据充分程度依次比较。"})
            except DomainError as exc:
                results.append({"job_ref":index+1,"error":exc.message})
        valid = sorted([r for r in results if "error" not in r],key=lambda r:key_tuple(r["sort_key"]),reverse=True)
        previous, rank = None, 0
        for index, r in enumerate(valid):
            current = key_tuple(r["sort_key"])
            if current!=previous: rank=index+1
            r["rank"],previous=rank,current
        return self.db.insert("job_comparison_runs",{"job_texts":[{"text":t,"pasted_at":now()} for t in data.job_texts],"ranked_results":valid,"errors":[r for r in results if "error" in r],"rubric_version":self.config.get("rubric")["version"]},actor,resume["data_origin"],resume_id=resume["id"])

    def build_benchmark(self, job_id, actor):
        self.writable(); self.enterprise(actor)
        job = self.owned("job_profiles",job_id,actor)
        pool = [j for j in self.db.list("job_profiles",owner=actor) if j["status"]=="已确认" and j["profile"]["direction"]==job["profile"]["direction"] and j["data_origin"]==job["data_origin"]]
        created = []
        for req in job["profile"]["requirements"]:
            levels = [r["required_level"] for j in pool for r in j["profile"]["requirements"] if r["skill"]==req["skill"]]
            if len(levels)<20: continue
            created.append(self.db.insert("role_benchmarks",{"skill":req["skill"],"sample_size":len(levels),"distribution":dict(Counter(map(str,levels))),"lower_level":min(levels),"upper_level":max(levels),"source_type":"B_synthetic" if job["data_origin"]=="synthetic" else "A_derived","rubric_version":self.config.get("rubric")["version"]},actor,job["data_origin"],job_id=job_id))
        return {"records":created,"message":"基准已生成" if created else "同类岗位样本不足，暂不生成基准"}

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
                order = ["match_results","job_comparison_runs","fit_reports","calibration_memory","review_events","ability_reports","batches","jd_diagnoses","hiring_briefs","role_benchmarks","preference_submissions","resumes","candidates","job_profiles"]
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
