import io
import json
from contextlib import asynccontextmanager
from typing import Annotated
from fastapi import FastAPI, Depends, Header, UploadFile, File, Form, Body
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from pypdf import PdfReader
from .errors import DomainError
from .models import *
from .service import TalentService
from .settings import Settings
from .seed import seed, PEOPLE
from .security import redact


def actor(x_demo_actor: Annotated[str | None, Header()] = None):
    value=x_demo_actor or "enterprise:demo"
    if not value.startswith(("enterprise:","candidate:")) or len(value)>100: raise DomainError("ACTOR_INVALID","无效的演示视角")
    return value


def create_app(settings=None):
    svc=TalentService(settings or Settings())
    @asynccontextmanager
    async def lifespan(app):
        if svc.settings.auto_seed: seed(svc)
        yield
    api=FastAPI(title="同频 · 人才发掘 Agent 系统",version="0.1.0",lifespan=lifespan)
    api.state.service=svc
    @api.exception_handler(DomainError)
    async def domain_error(request,exc):
        return JSONResponse(status_code=exc.status,content={"detail":{"code":exc.code,"message":exc.message}})
    @api.exception_handler(RequestValidationError)
    async def validation_error(request,exc):
        return JSONResponse(status_code=422,content={"detail":{"code":"VALIDATION_ERROR","message":"输入格式不正确，请检查必填字段、长度与选项","fields":[{"field":".".join(map(str,e["loc"])),"message":e["msg"]} for e in exc.errors()]}})

    Actor=Annotated[str,Depends(actor)]
    @api.get("/health")
    def health(): return {"status":"ok","env":svc.settings.env,"llm_mode":svc.settings.llm_mode,"llm_configured":bool(svc.settings.api_key),"vector_enabled":svc.settings.vector,"maintenance":svc.maintenance,"authentication":"demo-identity-only"}
    @api.get("/demo/people")
    def people():
        return [{"actor":p["actor"],"name":p["name"],"subtitle":p["subtitle"]} for p in PEOPLE] if svc.settings.env!="prod" else []
    @api.post("/demo/seed")
    def demo_seed(user:Actor):
        svc.enterprise(user);svc.writable();seed(svc)
        return {"status":"ok"}
    @api.get("/jobs")
    def jobs(user:Actor):
        rows=svc.db.list("job_profiles",owner=user) if user.startswith("enterprise:") else [r for r in svc.db.list("job_profiles") if r["status"]=="已确认" and (r["owner"].startswith("enterprise:") or r["owner"]==user)]
        return rows
    @api.post("/jobs")
    def create_job(data:JobInput,user:Actor): return svc.create_job(data,user)
    @api.get("/jobs/{id}/profile")
    def profile(id:str,user:Actor):
        job=svc.db.get("job_profiles",id)
        if not job or (job["owner"]!=user and not (user.startswith("candidate:") and job["status"]=="已确认" and job["owner"].startswith("enterprise:"))): raise DomainError("NOT_FOUND","岗位不存在",404)
        return job
    @api.put("/jobs/{id}/confirm")
    def confirm(id:str,data:JobConfirmation,user:Actor): return svc.confirm_job(id,data,user)
    @api.get("/resumes")
    def resumes(user:Actor): return [svc.public_resume(r) for r in svc.db.list("resumes",owner=user)]
    @api.post("/resumes")
    def create_resume(data:ResumeInput,user:Actor): return svc.create_resume(data,user)
    @api.post("/resumes/batch")
    async def upload(user:Actor, files:list[UploadFile]=File(...),data_origin:Origin=Form("synthetic")):
        result,errors=[],[]
        for file in files:
            try:
                content=await file.read(10*1024*1024+1)
                if len(content)>10*1024*1024: raise DomainError("FILE_TOO_LARGE","单份文件不能超过 10MB")
                name=(file.filename or "简历").rsplit(".",1)[0][:40]
                if (file.filename or "").lower().endswith(".pdf"):
                    reader=PdfReader(io.BytesIO(content))
                    text="\n".join(page.extract_text() or "" for page in reader.pages)
                    if not text.strip(): raise DomainError("OCR_REQUIRED","扫描 PDF 没有可提取文字，请先转换为文本")
                elif (file.filename or "").lower().endswith(".json"):
                    obj=json.loads(content.decode("utf-8-sig"));text=obj.get("text","");name=obj.get("name",name)
                elif (file.filename or "").lower().endswith(".txt"): text=content.decode("utf-8-sig")
                else: raise DomainError("FILE_TYPE","仅支持 PDF、JSON 和 TXT")
                result.append(svc.create_resume(ResumeInput(name=name,text=text,data_origin=data_origin),user))
            except Exception as exc:
                errors.append({"filename":file.filename,"message":exc.message if isinstance(exc,DomainError) else "文件解析失败，请检查格式并手工录入"})
        return {"resumes":result,"errors":errors}
    @api.post("/batches/run")
    def batch(data:dict,user:Actor): return svc.batch(data.get("job_id",""),user)
    @api.get("/batches")
    def batches(job_id:str,user:Actor):
        svc.owned("job_profiles",job_id,user)
        rows=svc.db.list("batches",owner=user,job_id=job_id); latest={}
        for r in rows: latest.setdefault(r["resume_id"],r)
        return list(latest.values())
    @api.post("/assessments")
    def assessments(data:AssessmentInput,user:Actor): return svc.assess(data,user)
    @api.get("/assessments")
    def list_reports(user:Actor,job_id:str|None=None):
        svc.enterprise(user)
        return svc.db.list("ability_reports",owner=user,**({"job_id":job_id} if job_id else {}))
    @api.get("/assessments/{id}")
    def report(id:str,user:Actor): return svc.owned("ability_reports",id,user)
    @api.post("/assessments/{id}/rerun")
    def rerun(id:str,user:Actor):
        r=svc.owned("ability_reports",id,user)
        if r["status"]!="已打回": raise DomainError("REPORT_LOCKED","请先打回旧报告后再重新分析",409)
        return svc.assess(AssessmentInput(job_id=r["job_id"],resume_ids=[r["resume_id"]]),user)
    @api.post("/assessments/{id}/followups")
    def followups(id:str,user:Actor): return svc.followups(id,user)
    @api.post("/reviews")
    def review(data:ReviewInput,user:Actor): return svc.review(data,user)
    @api.get("/reviews")
    def reviews(report_id:str,user:Actor):
        svc.owned("ability_reports",report_id,user)
        return svc.db.list("review_events",owner=user,report_id=report_id)
    @api.get("/candidates/ranking")
    def ranking(job_id:str,user:Actor): return svc.ranking(job_id,user)
    @api.get("/candidates/export")
    def export(job_id:str,user:Actor): return Response("\ufeff"+svc.csv_export(svc.ranking(job_id,user)),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=candidates.csv"})
    @api.post("/preferences/submit")
    def preferences(data:PreferenceInput,user:Actor): return svc.submit_preference(data,user)
    @api.get("/preferences")
    def get_preferences(user:Actor): return svc.db.list("preference_submissions",owner=user)
    @api.get("/preferences/{job_id}/enterprise")
    def get_ent_preferences(job_id:str,user:Actor):
        svc.owned("job_profiles",job_id,user)
        return svc.latest_preference("enterprise",job_id)
    @api.post("/matches/run")
    def match(data:MatchInput,user:Actor): return svc.run_match(data,user)
    @api.get("/matches")
    def matches(user:Actor): return svc.visible_matches(user)
    @api.get("/matches/participants")
    def participants(job_id:str,user:Actor):
        svc.enterprise(user);svc.owned("job_profiles",job_id,user)
        ids=set();rows=[]
        for p in svc.db.list("preference_submissions"):
            if p["side"]!="candidate" or p["resume_id"] in ids: continue
            ids.add(p["resume_id"])
            if p["share_with_counterparty"]:
                r=svc.db.get("resumes",p["resume_id"])
                if r: rows.append({"id":r["id"],"display_name":r["display_name"],"data_origin":r["data_origin"]})
        return rows
    @api.get("/matches/{id}")
    def match_detail(id:str,user:Actor):
        row=next((r for r in svc.visible_matches(user) if r["id"]==id),None)
        if not row: raise DomainError("NOT_FOUND","对照结果不存在",404)
        return row
    @api.post("/requirements/clarify")
    def clarify(data:dict,user:Actor): return svc.clarify(data.get("job_id",""),user)
    @api.post("/requirements/brief")
    def brief(data:BriefInput,user:Actor): return svc.brief(data,user)
    @api.get("/requirements/brief/{job_id}")
    def brief_read(job_id:str,user:Actor):
        svc.owned("job_profiles",job_id,user)
        return svc.db.list("hiring_briefs",owner=user,job_id=job_id)
    @api.post("/requirements/diagnose")
    def diagnose(data:dict,user:Actor):
        svc.writable();svc.enterprise(user)
        j=svc.owned("job_profiles",data.get("job_id",""),user)
        return svc.db.insert("jd_diagnoses",svc.diagnose(j,user),user,j["data_origin"],job_id=j["id"])
    @api.get("/requirements/coverage/{job_id}")
    def coverage(job_id:str,user:Actor):
        svc.owned("job_profiles",job_id,user)
        rows=svc.db.list("hiring_briefs",owner=user,job_id=job_id)
        return {"uncovered":[r for r in rows[0]["requirements"] if r["priority"]=="P0" and not r["assessable"]] if rows else [],"message":"请先保存需求画像" if not rows else "技能要求已有证据判据覆盖"}
    @api.post("/fit/analyze")
    def fit(data:FitInput,user:Actor): return svc.fit(data,user)
    @api.get("/fit/reports")
    def fits(user:Actor):
        svc.candidate(user)
        return svc.db.list("fit_reports",owner=user)
    @api.post("/compare/rank")
    def compare(data:CompareInput,user:Actor): return svc.compare(data,user)
    @api.get("/compare/runs")
    def comparisons(user:Actor):
        svc.candidate(user)
        return svc.db.list("job_comparison_runs",owner=user)
    @api.get("/fit/benchmark")
    def benchmark(job_id:str,user:Actor):
        job=svc.db.get("job_profiles",job_id)
        if not job or job["status"]!="已确认" or (job["owner"].startswith("candidate:") and job["owner"]!=user): raise DomainError("NOT_FOUND","公开岗位不存在",404)
        rows=svc.db.list("role_benchmarks",owner=job["owner"],job_id=job_id)
        rows=[r for r in rows if r["sample_size"]>=20 and r["rubric_version"]==svc.config.get("rubric")["version"]]
        if not rows: raise DomainError("INSUFFICIENT_SAMPLES","样本不足，暂不展示基准",422)
        return rows
    @api.post("/benchmarks/build")
    def build_benchmark(data:dict,user:Actor): return svc.build_benchmark(data.get("job_id",""),user)
    @api.get("/memory")
    def memory(user:Actor):
        svc.enterprise(user)
        return svc.db.list("calibration_memory",owner=user)
    @api.put("/memory/{id}")
    def memory_confirm(id:str,data:dict,user:Actor):
        svc.writable();svc.owned("calibration_memory",id,user)
        if data.get("action") not in {"confirm","delete"}: raise DomainError("ACTION_INVALID","请选择确认或删除")
        return svc.db.update("calibration_memory",id,{"confirmed":True} if data["action"]=="confirm" else {"deleted_at":__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()})
    @api.post("/assessments/resume-job/{job_id}")
    def resume_job(job_id:str,user:Actor):
        svc.writable();svc.owned("job_profiles",job_id,user)
        svc.db.audit("分析恢复",{"job_id":job_id},user)
        return {"status":"ok"}
    @api.get("/config/packs")
    @api.get("/config/packs/export")
    def pack(user:Actor):
        svc.enterprise(user)
        return svc.config.pack()
    @api.post("/config/packs/import")
    def pack_import(data:dict,user:Actor):
        svc.writable();svc.enterprise(user)
        value=svc.config.import_pack(data)
        svc.db.audit("配置变更",{"pack_version":value["pack_version"]},user)
        return value
    @api.get("/config/{name}")
    def config(name:str,user:Actor): return svc.config.get(name)
    @api.put("/config/{name}")
    def save_config(name:str,data:dict,user:Actor):
        svc.writable();svc.enterprise(user)
        result=svc.config.save(name,data)
        svc.db.audit("配置变更",{"config":name,"version":data["version"]},user)
        return result
    @api.get("/audit/summary")
    def audit(user:Actor):
        svc.enterprise(user)
        rows=svc.db.list("audit_logs",owner=user)
        return {"logs":rows,"cost_cny":round(sum(r["detail"].get("cost_cny",0) for r in rows),6),"alerts":sum(r["result"]=="告警" for r in rows),"model_mode":svc.settings.llm_mode}
    @api.get("/audit/export")
    def audit_export(user:Actor):
        svc.enterprise(user)
        rows=svc.db.list("audit_logs",owner=user)
        md="# 审计记录\n\n"+"\n".join(f"- {r['created_at']} · {r['event_type']} · {r['result']} · {json.dumps(r['detail'],ensure_ascii=False)}" for r in rows)
        return Response(md,media_type="text/markdown; charset=utf-8")
    @api.post("/audit/bias-check")
    def bias_check(user:Actor):
        svc.writable();svc.enterprise(user)
        pairs=[("性别：男\n年龄：22\n学校：甲大学\n", "性别：女\n年龄：25\n学校：乙大学\n"),("民族：汉族\n婚育：未婚\n","民族：其他\n婚育：已婚\n")]
        base="专业：软件工程\n课程项目使用 Python 实现统计功能"
        results=[{"pair":i+1,"sanitized_inputs_equal":redact(a+base)==redact(b+base)} for i,(a,b) in enumerate(pairs)]
        svc.db.audit("敏感属性隔离检查",{"pairs":results,"scope":"输入隔离检查；不等同于模型偏见评测"},user,"正常" if all(r["sanitized_inputs_equal"] for r in results) else "告警")
        return {"pairs":results,"note":"这是输入隔离检查。模型偏见需使用标注对照集另行验证。"}
    @api.post("/audit/drift-check")
    def drift(user:Actor):
        svc.writable();svc.enterprise(user)
        reports=svc.db.list("ability_reports",owner=user)
        anchors={}
        for r in reports:
            if r["status"]=="已确认": anchors.setdefault((r["job_id"],r["resume_id"]),r)
        if len(anchors)<10:
            svc.db.audit("漂移监控",{"skipped":True,"reason":"锚定样本少于十份"},user)
            return {"skipped":True,"message":"锚定样本不足十份，已记录跳过原因"}
        counts={}; totals={}
        for r in list(anchors.values())[:20]:
            j=svc.owned("job_profiles",r["job_id"],user);resume=svc.owned("resumes",r["resume_id"],user)
            current=svc.evaluate(j,resume,user)
            for d in r["dimensions"]:
                new=next((v for v in current["dimensions"] if v["dimension_id"]==d["dimension_id"]),None)
                id=d["dimension_id"];totals[id]=totals.get(id,0)+1;counts[id]=counts.get(id,0)+int(not new or new["tier"]!=d["tier"])
        rates={k:counts[k]/v for k,v in totals.items()}
        svc.db.audit("漂移监控",{"rates":rates,"rubric_version":svc.config.get("rubric")["version"],"model":svc.settings.model,"prompt_version":"evidence-1.0"},user,"告警" if any(r>.2 for r in rates.values()) else "正常")
        return {"rates":rates,"skipped":False}
    @api.post("/selfcheck/identifiability")
    def selfcheck(user:Actor):
        svc.enterprise(user)
        labels=[("后端开发","Python 后端服务开发"),("前端开发","React 前端页面开发"),("数据与算法","机器学习算法应用开发")]
        from .deterministic import parse_jd
        rows=[{"expected":label,"actual":parse_jd(text)["direction"]} for label,text in labels]
        return {"fixture_examples":rows,"fixture_accuracy":sum(r["expected"]==r["actual"] for r in rows)/len(rows),"note":"仅内置规则冒烟检查；未加载人工标注集，不宣称画像可辨识率达标。"}
    @api.post("/maintenance/purge")
    def purge(data:dict,user:Actor):
        if data.get("confirmation")!="清理合成数据": raise DomainError("PURGE_CONFIRM","请填写完整确认语句")
        return svc.purge(data.get("env"),user)
    return api


app=create_app()
