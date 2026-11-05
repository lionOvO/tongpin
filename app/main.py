import io
import json
import asyncio
import threading
import time
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Annotated
from fastapi import FastAPI, Depends, Request, UploadFile, File, Form, Body, Query
from fastapi.responses import JSONResponse, Response, FileResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from pypdf import PdfReader
from starlette.concurrency import run_in_threadpool
from .errors import DomainError
from .models import *
from .service import TalentService
from .settings import Settings
from .seed import seed, seed_account
from .security import redact
from .auth import Auth, SmsInput, PhoneLogin, PasswordLogin, Registration, PasswordReset, WorkspaceInput
from .service import current_actor
from .assessment_tasks import AssessmentTasks, ReportTaskInput
from .comparison_tasks import ComparisonTasks, ComparisonTaskInput, ComparisonRetryInput
from .job_fit import refresh_fit_result
from .enterprise_verification import EnterpriseReview
from .platform_admin import PlatformAdmin, ModerationInput
from .hiring import Hiring, ApplyInput, HiringAction, HiringMessage, ConversationRead, ApplicationResumeImport
from .video_calls import VideoCalls, CallStart, CallAction, CallSync, CallSignal
from uuid import UUID
from .recruiter_review import RecruiterReview, RecruiterReviewInput
from .recruiter_assistant import RecruiterAssistant, RecruiterTurn, RecruiterWorkspaceUpdate, RecruiterCancel
from .ai_workspace import AIWorkspace, WorkspaceCreate, WorkspaceTurn, WorkspaceCancel, WorkspaceNote, WorkspaceAddition, DraftConfirmation, WorkspaceModel, WorkspaceMaterialEdit, WorkspaceMaterialDecision
from .workspace_jobs import WorkspaceJobs
from .workspace_stream import WorkspaceStreams


def create_app(settings=None):
    svc=TalentService(settings or Settings())
    auth=Auth(svc.settings)
    svc.enterprise_owner_verified=auth.enterprise_owner_verified
    svc.enterprise_company_name=auth.enterprise_company_name
    svc.enterprise_hiring_enabled=lambda actor: auth.actor_active(actor) and auth.enterprise_owner_verified(actor)
    hiring=Hiring(svc,auth)
    video_calls=VideoCalls(hiring)
    report_tasks=AssessmentTasks(svc,auth)
    comparison_tasks=ComparisonTasks(svc,auth)
    svc.application_resume_available=hiring.imported_resume_available
    recruiter_review=RecruiterReview(hiring)
    recruiter_assistant=RecruiterAssistant(recruiter_review)
    platform=PlatformAdmin(svc,auth)
    workspace=AIWorkspace(svc)
    workspace.jobs=WorkspaceJobs(workspace,comparison_tasks)
    workspace_streams=WorkspaceStreams()
    document_workers=ThreadPoolExecutor(max_workers=2,thread_name_prefix='resume-parser')
    document_slots=threading.BoundedSemaphore(2)

    def parse_document(content, filename):
        name=(filename or '简历').rsplit('.',1)[0][:40]
        if filename.lower().endswith('.pdf'):
            reader=PdfReader(io.BytesIO(content))
            if len(reader.pages)>50: raise DomainError('PDF_PAGES','单份 PDF 最多 50 页。',422)
            started=time.monotonic(); paragraphs=[]; size=0
            for page in reader.pages:
                paragraph=page.extract_text() or ''; size+=len(paragraph)
                if size>50000: raise DomainError('DOCUMENT_LENGTH','简历正文最多 50000 字，请精简后导入。',422)
                paragraphs.append(paragraph)
                if time.monotonic()-started>20: raise DomainError('DOCUMENT_TIMEOUT','文件解析超时，请转换为 TXT 或手工录入。',422)
            text='\n'.join(paragraphs)
            if not text.strip(): raise DomainError('OCR_REQUIRED','扫描 PDF 没有可提取文字，请先转换为文本')
        elif filename.lower().endswith(('.doc', '.docx')):
            from .word_documents import extract_word
            text = extract_word(content, filename)
        elif filename.lower().endswith('.json'):
            obj=json.loads(content.decode('utf-8-sig'));text=obj.get('text','');name=obj.get('name',name)
        elif filename.lower().endswith('.txt'): text=content.decode('utf-8-sig')
        else: raise DomainError('FILE_TYPE','仅支持 PDF、DOC、DOCX、JSON 和 TXT')
        return name,text

    async def parse_upload(content, filename):
        if not document_slots.acquire(blocking=False):
            raise DomainError('DOCUMENT_BUSY','当前文件解析任务较多，请稍后重试。',429)
        future=document_workers.submit(parse_document,content,filename)
        future.add_done_callback(lambda _:document_slots.release())
        wrapped=asyncio.wrap_future(future)
        wrapped.add_done_callback(lambda done:done.exception() if not done.cancelled() else None)
        try:
            return await asyncio.wait_for(asyncio.shield(wrapped),timeout=20)
        except asyncio.TimeoutError:
            raise DomainError('DOCUMENT_TIMEOUT','文件解析超时，请转换为 TXT 或手工录入。',422) from None
    def candidate_actor(request:Request):
        if auth.request_scope(request) != 'user':
            raise DomainError('AI_USER_SESSION_REQUIRED','AI 工作区仅使用求职者端的独立会话。',403)
        actor=auth.actor(request)
        svc.candidate(actor)
        return actor
    def hiring_actor(request:Request):
        if auth.request_scope(request) != 'user':
            raise DomainError('HIRING_USER_SESSION', '投递与沟通仅使用普通用户的独立会话。', 403)
        session=auth.session(request)
        if session['account_role']=='admin':
            raise DomainError('HIRING_USER_SESSION', '平台工作人员不能代替企业或求职者参与投递。', 403)
        return session['actor']
    def recruiter_actor(request:Request):
        actor = hiring_actor(request)
        svc.enterprise(actor)
        if not svc.enterprise_hiring_enabled(actor):
            raise DomainError('ENTERPRISE_VERIFICATION_REQUIRED', '请完成企业认证后使用招聘资料卡。', 403)
        return actor
    @asynccontextmanager
    async def lifespan(app):
        if svc.settings.auto_seed: seed(svc)
        report_tasks.start()
        comparison_tasks.start()
        workspace_streams.start()
        try: yield
        finally:
            document_workers.shutdown(wait=False,cancel_futures=True)
            report_tasks.close()
            comparison_tasks.close()
            workspace_streams.close()
    api=FastAPI(title="同频 · 人才发掘 Agent 系统",version="0.1.0",lifespan=lifespan)
    api.state.service=svc
    api.state.auth=auth
    api.state.video_calls=video_calls
    api.state.report_tasks=report_tasks
    api.state.comparison_tasks=comparison_tasks
    api.state.recruiter_assistant=recruiter_assistant
    @api.middleware("http")
    async def private_response(request, call_next):
        actor = "system"
        try: actor = auth.session(request, unsafe=False)["actor"]
        except DomainError: pass
        token = current_actor.set(actor)
        try:
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        finally: current_actor.reset(token)
    @api.exception_handler(DomainError)
    async def domain_error(request,exc):
        return JSONResponse(status_code=exc.status,content={"detail":{"code":exc.code,"message":exc.message}})
    @api.exception_handler(RequestValidationError)
    async def validation_error(request,exc):
        return JSONResponse(status_code=422,content={"detail":{"code":"VALIDATION_ERROR","message":"输入格式不正确，请检查必填字段、长度与选项","fields":[{"field":".".join(map(str,e["loc"])),"message":e["msg"]} for e in exc.errors()]}})

    Actor=Annotated[str,Depends(auth.actor)]
    Admin=Annotated[str,Depends(auth.admin)]
    Candidate=Annotated[str,Depends(candidate_actor)]
    HiringActor=Annotated[str,Depends(hiring_actor)]
    Recruiter=Annotated[str,Depends(recruiter_actor)]
    @api.get('/video-calls/active')
    def active_video_calls(user:HiringActor,client_id:UUID): return video_calls.active(user,client_id)
    @api.get('/video-calls')
    def video_call_history(user:HiringActor,application_id:str=Query(min_length=1,max_length=100)):
        return video_calls.history(application_id,user)
    @api.post('/video-calls')
    def start_video_call(data:CallStart,user:HiringActor): return video_calls.start(data,user)
    @api.post('/video-calls/{id}/actions')
    def video_call_action(id:str,data:CallAction,user:HiringActor): return video_calls.action(id,data,user)
    @api.post('/video-calls/{id}/sync')
    def sync_video_call(id:str,data:CallSync,user:HiringActor): return video_calls.sync(id,data,user)
    @api.post('/video-calls/{id}/signals')
    def video_call_signal(id:str,data:CallSignal,user:HiringActor): return video_calls.signal(id,data,user)
    @api.get('/recruiter/models')
    def recruiter_models(user:Recruiter): return {**svc.models.public(), 'default_model_id': 'deepseek'}
    @api.post('/assessment-tasks', status_code=202)
    def start_report_task(data:ReportTaskInput,user:Recruiter): return report_tasks.submit(data,user)
    @api.get('/assessment-tasks')
    def list_report_tasks(job_id:str,user:Recruiter): return report_tasks.list(job_id,user)
    @api.get('/assessment-tasks/{id}')
    def report_task(id:str,user:Recruiter): return report_tasks.get(id,user)
    @api.get('/resumes/applicants')
    def applicant_resumes(user:Recruiter,job_id:str|None=None,offset:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=50),q:str=Query('',max_length=100)):
        return hiring.resume_candidates(user,job_id=job_id,offset=offset,limit=limit,query=q)
    @api.post('/applications/{id}/resume-import')
    def import_applicant_resume(id:str,data:ApplicationResumeImport,user:Recruiter): return hiring.import_resume(id,data,user)
    def text_resume_response(name,text):
        filename=quote(''.join(c for c in name if c not in '/\\\r\n')[:80]+'.txt',safe='')
        return Response('\ufeff'+text,media_type='text/plain; charset=utf-8',headers={'Content-Disposition':"attachment; filename=resume.txt; filename*=UTF-8''"+filename})
    @api.get('/applications/{id}/resume-download')
    def download_applicant_resume(id:str,user:Recruiter):
        snapshot=hiring.download_resume(id,user)
        return text_resume_response(snapshot['name'],snapshot['text'])
    @api.get('/applications/{id}/recruiter-review')
    def recruiter_card(id:str,user:Recruiter): return recruiter_review.get(id,user)
    @api.post('/applications/{id}/recruiter-review')
    def recruiter_analyze(id:str,data:RecruiterReviewInput,request:Request,user:Recruiter):
        return recruiter_review.analyze(id,data,user,authorize=lambda:recruiter_actor(request))
    @api.get('/applications/{id}/recruiter-assistant')
    def recruiter_chat(id:str,user:Recruiter,session_id:UUID|None=None): return recruiter_assistant.get(id,user,session_id)
    @api.post('/applications/{id}/recruiter-assistant/workspace')
    def recruiter_workspace(id:str,data:RecruiterWorkspaceUpdate,user:Recruiter): return recruiter_assistant.update(id,data,user)
    @api.post('/applications/{id}/recruiter-assistant/turns')
    def recruiter_turn(id:str,data:RecruiterTurn,request:Request,user:Recruiter):
        return recruiter_assistant.turn(id,data,user,authorize=lambda:recruiter_actor(request))
    @api.post('/applications/{id}/recruiter-assistant/turns/stream')
    def recruiter_turn_stream(id:str,data:RecruiterTurn,request:Request,user:Recruiter):
        recruiter_review.owned(id,user)
        authorize=lambda:recruiter_actor(request)
        return StreamingResponse(workspace_streams.open(
            lambda emit:recruiter_assistant.turn(id,data,user,authorize=authorize,emit=emit),authorize),
            media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
    @api.post('/applications/{id}/recruiter-assistant/cancel')
    def recruiter_cancel(id:str,data:RecruiterCancel,user:Recruiter): return recruiter_assistant.cancel(id,data,user)
    @api.get('/applications')
    def applications(user:HiringActor,job_id:str|None=None): return hiring.list(user,job_id)
    @api.get('/applications/page')
    def application_page(user:HiringActor,offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100),job_id:str|None=None,
                         q:str=Query('',max_length=100),status:Literal['all','submitted','invited','accepted','ended']='all'):
        return hiring.page(user,offset=offset,limit=limit,job_id=job_id,query=q,status=status)
    @api.get('/messages/conversations')
    def conversations(user:HiringActor,q:str=Query(default='',max_length=100)): return hiring.conversations(user,q)
    @api.get('/messages/conversations/page')
    def conversation_page(user:HiringActor,offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100),q:str=Query('',max_length=100)):
        return {**hiring.page(user,offset=offset,limit=limit,query=q,conversations=True),'unread_total':hiring.unread_total(user)}
    @api.get('/messages/unread')
    def unread_messages(user:HiringActor): return {'total':hiring.unread_total(user)}
    @api.post('/messages/conversations/{id}/read')
    def conversation_read(id:str,data:ConversationRead,user:HiringActor): return hiring.read(id,data,user)
    @api.post('/applications')
    def apply_job(data:ApplyInput,user:HiringActor): return hiring.apply(data,user)
    @api.get('/applications/{id}')
    def application_detail(id:str,user:HiringActor): return hiring.public(hiring.owned(id,user),user,True)
    @api.post('/applications/{id}/actions')
    def application_action(id:str,data:HiringAction,user:HiringActor): return hiring.change(id,data,user)
    @api.post('/applications/{id}/messages')
    def application_message(id:str,data:HiringMessage,user:HiringActor): return hiring.change(id,data,user,True)
    @api.get('/ai/models')
    def ai_models(user:Candidate): return svc.models.public()
    @api.get('/ai/workspaces')
    def ai_workspaces(user:Candidate): return workspace.list(user)
    @api.post('/ai/workspaces')
    def ai_create(data:WorkspaceCreate,user:Candidate): return workspace.create(data,user)
    @api.get('/ai/workspaces/{id}')
    def ai_detail(id:str,user:Candidate): return workspace.public(workspace.owned(id,user),user)
    @api.delete('/ai/workspaces/{id}')
    def ai_delete(id:str,user:Candidate): return workspace.delete(id,user)
    @api.post('/ai/workspaces/{id}/turns')
    def ai_turn(id:str,data:WorkspaceTurn,request:Request,user:Candidate): return workspace.turn(id,data,user,authorize=lambda:candidate_actor(request))
    @api.post('/ai/workspaces/{id}/turns/stream')
    def ai_turn_stream(id:str,data:WorkspaceTurn,request:Request,user:Candidate):
        workspace.owned(id,user)
        authorize=lambda:candidate_actor(request)
        return StreamingResponse(workspace_streams.open(
            lambda emit:workspace.turn(id,data,user,authorize=authorize,emit=emit),authorize),
            media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
    @api.post('/ai/workspaces/{id}/cancel')
    def ai_cancel(id:str,data:WorkspaceCancel,user:Candidate): return workspace.cancel(id,data,user)
    @api.post('/ai/workspaces/{id}/model')
    def ai_select_model(id:str,data:WorkspaceModel,user:Candidate): return workspace.select_model(id,data,user)
    @api.post('/ai/workspaces/{id}/notes')
    def ai_note(id:str,data:WorkspaceNote,user:Candidate): return workspace.note(id,data,user)
    @api.post('/ai/workspaces/{id}/additions')
    def ai_addition(id:str,data:WorkspaceAddition,user:Candidate): return workspace.add_note(id,data.text,data.expected_version,user)
    @api.post('/ai/workspaces/{id}/materials/edit')
    def ai_edit_material(id:str,data:WorkspaceMaterialEdit,user:Candidate): return workspace.edit_material(id,data,user)
    @api.post('/ai/workspaces/{id}/materials/resolve')
    def ai_resolve_materials(id:str,data:WorkspaceMaterialDecision,user:Candidate): return workspace.resolve_materials(id,data,user)
    @api.post('/ai/workspaces/{id}/drafts/confirm')
    def ai_confirm(id:str,data:DraftConfirmation,user:Candidate): return workspace.confirm(id,data,user)
    @api.get("/auth/options")
    def auth_options():
        return {"sms_available":not bool(auth.sms.missing()), "missing":auth.sms.missing()}
    @api.post("/auth/sms/send")
    def send_code(data:SmsInput,request:Request): return auth.send(data,request)
    @api.post("/auth/login/phone")
    def login_phone(data:PhoneLogin,request:Request,response:Response): return auth.login(data,request,response)
    @api.post("/auth/register")
    def register(data:Registration,request:Request,response:Response): return auth.register(data,request,response)
    @api.post("/auth/login/password")
    def login_password(data:PasswordLogin,request:Request,response:Response): return auth.login_password(data,request,response)
    @api.post("/auth/admin/login/password")
    def admin_password(data:PasswordLogin,request:Request,response:Response): return auth.login_password(data,request,response,admin_only=True)
    @api.post("/auth/admin/login/phone")
    def admin_phone(data:PhoneLogin,request:Request,response:Response): return auth.login(data,request,response,admin_only=True)
    @api.post("/auth/password/reset")
    def reset_password(data:PasswordReset,request:Request,response:Response): return auth.reset_password(data,request,response)
    @api.get("/auth/admin/me")
    @api.get("/auth/me")
    def me(request:Request):
        row=auth.session(request)
        return {"user":auth.public(row),"csrf_token":row["csrf"]}
    @api.post("/auth/admin/password/reset")
    def admin_reset(data:PasswordReset,request:Request,response:Response): return auth.reset_password(data,request,response)
    @api.post("/auth/admin/logout")
    @api.post("/auth/logout")
    def logout(request:Request,response:Response): return auth.logout(request,response)
    @api.post("/auth/workspace")
    def switch_workspace(data:WorkspaceInput,request:Request,response:Response): return auth.switch_workspace(data,request,response)
    @api.get("/enterprise-verification")
    def my_verification(request:Request): return auth.verification.mine(auth.session(request))
    @api.post("/enterprise-verification")
    async def submit_verification(request:Request, company_name:str=Form(...),credit_code:str=Form(...),
                                  legal_representative:str=Form(...),contact_name:str=Form(...),
                                  license:UploadFile=File(...),authorization:UploadFile=File(...)):
        user=auth.session(request)
        fields={"company_name":company_name,"credit_code":credit_code,"legal_representative":legal_representative,"contact_name":contact_name}
        evidence=[]
        for file in (license,authorization):
            try: evidence.append((await file.read(5*1024*1024+1),file.filename))
            finally: await file.close()
        return auth.verification.submit(user,fields,*evidence)
    @api.get("/enterprise-verification/{id}/files/{kind}")
    def verification_file(id:str,kind:str,request:Request):
        viewer=auth.session(request)
        path,name=auth.verification.evidence(id,kind,viewer)
        if viewer.get('session_scope')=='admin': platform.record(viewer,'下载企业证明','enterprise-verification',id,'按审核职责下载 '+kind)
        return FileResponse(path,media_type="application/octet-stream",filename=name)
    @api.get("/enterprise-reviews")
    def enterprise_reviews(request:Request,user:Admin): return auth.verification.list(auth.session(request))
    @api.post("/enterprise-reviews/{id}")
    def review_enterprise(id:str,data:EnterpriseReview,request:Request,user:Admin):
        viewer=auth.session(request)
        result=auth.verification.review(id,data,viewer)
        platform.record(viewer,{'approve':'通过企业认证','reject':'退回企业认证','revoke':'撤销企业认证'}[data.decision],'enterprise-verification',id,data.reason.strip())
        return result
    @api.get('/admin/overview')
    def admin_overview(user:Admin):return platform.overview()
    @api.get('/admin/accounts')
    def admin_accounts(user:Admin,offset:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=50)):return platform.accounts(offset,limit)
    @api.get('/admin/records/{kind}')
    def admin_records(kind:Literal['jobs','resumes'],user:Admin,offset:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=50)):return platform.records(kind,offset,limit)
    @api.get('/admin/records/{kind}/{id}')
    def admin_detail(kind:Literal['jobs','resumes'],id:str,request:Request,user:Admin):return platform.detail(kind,id,auth.session(request))
    @api.post('/admin/accounts/{id}/{operation}')
    def admin_account_action(id:str,operation:Literal['suspend','restore'],data:ModerationInput,request:Request,user:Admin):return platform.account_action(id,operation=='suspend',data,auth.session(request))
    @api.post('/admin/jobs/{id}/{operation}')
    def admin_job_action(id:str,operation:Literal['hide','restore'],data:ModerationInput,request:Request,user:Admin):return platform.job_action(id,operation=='hide',data,auth.session(request))
    @api.get('/admin/events')
    def admin_events(user:Admin,offset:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=50)):return platform.events(offset,limit)
    @api.get('/admin/governance/jobs')
    def governance_jobs(request:Request,user:Admin,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),q:str=Query('',max_length=100)):
        return platform.governance_jobs(offset,limit,q,auth.session(request))
    @api.get('/admin/governance/audit')
    def governance_audit(request:Request,user:Admin,offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100)):
        return platform.governance_audit(offset,limit,auth.session(request))
    @api.get('/admin/governance/memory')
    def governance_memory(job_id:str,request:Request,user:Admin): return platform.governance_memory(job_id,auth.session(request))
    @api.get('/admin/governance/quality')
    def governance_quality(job_id:str,request:Request,user:Admin): return platform.governance_quality(job_id,auth.session(request))
    @api.post('/admin/governance/jobs/{id}/{operation}')
    def governance_job_action(id:str,operation:Literal['benchmark','resume','drift'],data:ModerationInput,request:Request,user:Admin):
        return platform.governance_job_action(id,operation,data,auth.session(request))
    @api.post('/admin/governance/memory/{id}/{operation}')
    def governance_memory_action(id:str,operation:Literal['confirm','delete'],data:ModerationInput,request:Request,user:Admin):
        return platform.governance_memory_action(id,operation,data,auth.session(request))
    @api.get("/health")
    def health(): return {"status":"ok","env":svc.settings.env,"llm_mode":svc.settings.llm_mode,"llm_configured":svc.models.resolve().public(svc.models.enabled)["available"],"llm_label":svc.models.resolve().label,"vector_enabled":svc.settings.vector,"maintenance":svc.maintenance,"authentication":"phone-session"}
    @api.get("/demo/people")
    def people(user:Admin): return []
    @api.post("/demo/seed")
    def demo_seed(user:Admin):
        svc.enterprise(user);svc.writable();seed_account(svc,user)
        return {"status":"ok"}
    @api.get("/jobs")
    def jobs(user:Actor):
        rows=svc.db.list("job_profiles",owner=user) if user.startswith("enterprise:") else [r for r in svc.db.list("job_profiles") if svc.job_visible(r,user)]
        return [svc.public_job(row,user) for row in rows]
    @api.post('/jobs/references')
    def create_reference_job(data:ReferenceJobInput,user:Annotated[str,Depends(candidate_actor)]):
        return svc.create_reference_job(data,user)
    @api.post("/jobs")
    def create_job(data:JobInput,user:Actor): return svc.create_job(data,user)
    @api.get("/jobs/{id}/profile")
    def profile(id:str,user:Actor):
        job=svc.db.get("job_profiles",id)
        if not job or not svc.job_visible(job,user): raise DomainError("NOT_FOUND","岗位不存在",404)
        return svc.public_job(job,user)
    @api.put("/jobs/{id}/visibility")
    def visibility(id:str,data:JobVisibility,user:Actor):
        svc.writable();svc.enterprise(user)
        row=svc.owned("job_profiles",id,user)
        if data.published and row.get('moderation_status')=='suspended':raise DomainError('JOB_SUSPENDED','岗位已被平台暂停公开，请联系平台工作人员处理。',403)
        if data.published and row["status"]!="已确认": raise DomainError("PROFILE_UNCONFIRMED","请先确认岗位画像")
        row=svc.db.update("job_profiles",id,{"published":data.published})
        svc.db.audit("岗位可见性变更",{"job_id":id,"published":data.published},user)
        return row
    @api.put("/jobs/{id}/confirm")
    def confirm(id:str,data:JobConfirmation,user:Actor): return svc.confirm_job(id,data,user)
    @api.get("/resumes")
    def resumes(user:Actor): return [svc.public_resume(r) for r in svc.active_resumes(user)]
    @api.get('/resumes/{id}/download')
    def download_resume(id:str,user:Actor):
        row=svc.active_resume(id,user)
        svc.db.audit('简历文本下载',{'resume_id':id},user)
        return text_resume_response(row['display_name'],row['text'])
    @api.get('/resumes/{id}/original')
    def original_resume(id:str,user:Actor):
        path, metadata = svc.resume_original(id,user)
        svc.db.audit('简历原文件读取',{'resume_id':id},user)
        # Files are never exposed through a public static directory. Canvas previews
        # fetch with the current tab's authenticated headers; downloads stay private.
        return FileResponse(path,media_type=metadata['media_type'],filename=metadata['name'],
                            headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
    @api.delete("/resumes/{id}")
    def delete_resume(id:str,user:Actor): return svc.delete_resume(id,user)
    @api.post("/resumes")
    def create_resume(data:ResumeInput,user:Actor): return svc.create_resume(data,user)
    @api.post("/resumes/batch")
    async def upload(user:Actor, files:list[UploadFile]=File(...),data_origin:Origin=Form("synthetic")):
        if len(files)>50: raise DomainError("BATCH_TOO_LARGE","一次最多导入 50 份文件",422)
        svc.writable()
        result,errors=[],[]
        total_bytes=0
        for file in files:
            try:
                content=await file.read(10*1024*1024+1)
                total_bytes+=len(content)
                if total_bytes>50*1024*1024: raise DomainError("BATCH_TOO_LARGE","本批文件总量不能超过 50MB")
                if len(content)>10*1024*1024: raise DomainError("FILE_TOO_LARGE","单份文件不能超过 10MB")
                name,text=await parse_upload(content,file.filename or '')
                result.append(await run_in_threadpool(svc.create_resume,ResumeInput(name=name,text=text,data_origin=data_origin),user,(file.filename or 'resume.txt',content)))
            except Exception as exc:
                errors.append({"filename":file.filename,"message":exc.message if isinstance(exc,DomainError) else "文件解析失败，请检查格式并手工录入"})
            finally: await file.close()
        return {"resumes":result,"errors":errors}
    @api.post("/batches/run")
    def batch(data:dict,user:Actor): return svc.batch(data.get("job_id",""),user)
    @api.get("/batches")
    def batches(job_id:str,user:Actor):
        svc.owned("job_profiles",job_id,user)
        rows=svc.visible_material_records("batches",user,job_id=job_id); latest={}
        for r in rows: latest.setdefault(r["resume_id"],r)
        return list(latest.values())
    @api.post("/assessments")
    def assessments(data:AssessmentInput,user:Actor): return svc.assess(data,user)
    @api.get("/assessments")
    def list_reports(user:Actor,job_id:str|None=None):
        svc.enterprise(user)
        return svc.visible_material_records("ability_reports",user,**({"job_id":job_id} if job_id else {}))
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
        for m in (row for row in svc.visible_matches(user) if row['job_id'] == job_id):
            if m["resume_id"] in ids: continue
            ids.add(m["resume_id"])
            r=svc.db.get("resumes",m["resume_id"])
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
        job=svc.owned('job_profiles',job_id,user)
        brief=svc.current_brief(job)
        uncovered=[r for r in brief['requirements'] if not r['assessable']] if brief else []
        return {'uncovered':uncovered,'message':'请先保存当前画像的需求澄清' if not brief else f'{len(uncovered)} 项业务期待需要通过沟通或补充经历确认' if uncovered else '技能要求已有证据判据覆盖'}
    @api.post("/fit/analyze")
    def fit(data:FitInput,user:Actor): return svc.fit(data,user)
    @api.get("/fit/reports")
    def fits(user:Actor):
        svc.candidate(user)
        return [refresh_fit_result(row) for row in svc.db.list("fit_reports",owner=user)]
    @api.post("/compare/rank")
    def compare(data:CompareInput,user:Actor): return svc.compare(data,user)
    @api.get("/compare/runs")
    def comparisons(user:Actor):
        return comparison_tasks.list(user)
    @api.post('/compare/tasks', status_code=202)
    def comparison_submit(data:ComparisonTaskInput, user:Annotated[str,Depends(candidate_actor)]):
        return comparison_tasks.submit(data, user)
    @api.post('/compare/tasks/{id}/retry', status_code=202)
    def comparison_retry(id:str, data:ComparisonRetryInput, user:Annotated[str,Depends(candidate_actor)]):
        return comparison_tasks.retry(id, data, user)
    @api.get('/compare/tasks/{id}')
    def comparison_read(id:str, user:Annotated[str,Depends(candidate_actor)]):
        return comparison_tasks.get(id, user)
    @api.get("/fit/benchmark")
    def benchmark(job_id:str,user:Actor):
        job=svc.db.get("job_profiles",job_id)
        if not job or job["status"]!="已确认" or not svc.job_visible(job,user): raise DomainError("NOT_FOUND","公开岗位不存在",404)
        rows=svc.valid_benchmarks(job)
        if not rows: raise DomainError("INSUFFICIENT_SAMPLES","样本不足，暂不展示基准",422)
        return rows
    @api.post("/benchmarks/build")
    def build_benchmark(data:dict,user:Actor): return svc.build_benchmark(data.get("job_id",""),user)
    @api.get("/memory")
    def memory(user:Actor):
        svc.enterprise(user)
        return svc.visible_material_records("calibration_memory",user)
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
    def pack(user:Admin):
        svc.enterprise(user)
        return svc.config.pack()
    @api.post("/config/packs/import")
    def pack_import(data:dict,user:Admin):
        svc.writable();svc.enterprise(user)
        value=svc.config.import_pack(data)
        svc.db.audit("配置变更",{"pack_version":value["pack_version"]},user)
        return value
    @api.get("/config/{name}")
    def config(name:str,user:Actor): return svc.config.get(name)
    @api.put("/config/{name}")
    def save_config(name:str,data:dict,user:Admin):
        svc.writable();svc.enterprise(user)
        result=svc.config.save(name,data)
        svc.db.audit("配置变更",{"config":name,"version":data["version"]},user)
        return result
    @api.get("/audit/summary")
    def audit(user:Actor):
        svc.enterprise(user)
        rows=svc.db.list("audit_logs",owner=user)
        return {"logs":rows,"cost_cny":round(sum(r["detail"].get("cost_cny",0) for r in rows),6),"alerts":sum(r["result"]=="告警" for r in rows),"model_mode":svc.settings.llm_mode}
    @api.get('/quality/summary')
    def quality_summary(job_id:str,user:Actor): return svc.quality_summary(job_id,user)
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
        reports=svc.visible_material_records("ability_reports",user)
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
    def purge(data:dict,user:Admin):
        if data.get("confirmation")!="清理合成数据": raise DomainError("PURGE_CONFIRM","请填写完整确认语句")
        return svc.purge(data.get("env"),user)
    return api


app=create_app()
