"""Platform staff moderation: bounded listings, explicit reasons and access records."""
import time
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field
from .errors import DomainError
from .service import current_actor


class ModerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=5, max_length=1000)


class PlatformAdmin:
    def __init__(self, service, auth):
        self.svc=service; self.auth=auth
        with auth.tx() as cx:
            cx.execute("""CREATE TABLE IF NOT EXISTS platform_admin_events (
                id TEXT PRIMARY KEY, staff_id TEXT NOT NULL REFERENCES accounts(id),
                action TEXT NOT NULL, resource TEXT NOT NULL, resource_id TEXT NOT NULL,
                reason TEXT NOT NULL, created_at REAL NOT NULL)""")

    def record(self, user, action, resource, id, reason, cx=None):
        if cx is None:
            with self.auth.tx() as tx: self.record(user,action,resource,id,reason,tx)
            return
        cx.execute("INSERT INTO platform_admin_events VALUES (?,?,?,?,?,?,?)",(str(uuid4()),user['id'],action,resource,id,reason,time.time()))

    @staticmethod
    def reason(data):
        reason=data.reason.strip()
        if len(reason)<5: raise DomainError('MODERATION_REASON','请填写至少 5 个字符的处理依据。',422)
        return reason

    def overview(self):
        with self.auth.tx() as cx:
            accounts=cx.execute("SELECT COUNT(*) FROM accounts WHERE env=? AND role!='admin'",(self.auth.settings.env,)).fetchone()[0]
            suspended=cx.execute("SELECT COUNT(*) FROM accounts WHERE env=? AND disabled=1",(self.auth.settings.env,)).fetchone()[0]
            pending=cx.execute("""SELECT COUNT(*) FROM enterprise_submissions s JOIN accounts a ON a.id=s.account_id
                WHERE a.env=? AND s.status='pending' AND s.id=(SELECT id FROM enterprise_submissions WHERE account_id=s.account_id ORDER BY created_at DESC,id DESC LIMIT 1)""",(self.auth.settings.env,)).fetchone()[0]
        with self.svc.db.transaction() as cx:
            counts={table:cx.execute(f'SELECT COUNT(*) FROM {table} WHERE env=?',(self.auth.settings.env,)).fetchone()[0] for table in ['job_profiles','resumes','ability_reports','fit_reports']}
        return {'accounts':accounts,'suspended_accounts':suspended,'pending_verifications':pending,**counts}

    def accounts(self, offset, limit):
        with self.auth.tx() as cx:
            total=cx.execute('SELECT COUNT(*) FROM accounts WHERE env=?',(self.auth.settings.env,)).fetchone()[0]
            rows=cx.execute('SELECT * FROM accounts WHERE env=? ORDER BY created_at DESC,id LIMIT ? OFFSET ?',(self.auth.settings.env,limit,offset)).fetchall()
            items=[]
            for row in rows:
                qualification=self.auth.verification.latest(cx,row['id'])
                items.append({'id':row['id'],'name':row['phone'][:3]+'****'+row['phone'][-4:],'role':row['role'],'disabled':bool(row['disabled']),'created_at':row['created_at'],
                    'enterprise_status':qualification['status'] if qualification else 'unsubmitted','company_name':qualification['company_name'] if qualification else ''})
        return {'items':items,'total':total}

    def records(self, kind, offset, limit):
        table={'jobs':'job_profiles','resumes':'resumes'}[kind]
        with self.svc.db.transaction() as cx:
            total=cx.execute(f'SELECT COUNT(*) FROM {table} WHERE env=?',(self.auth.settings.env,)).fetchone()[0]
            rows=[self.svc.db.decode(row) for row in cx.execute(f'SELECT * FROM {table} WHERE env=? ORDER BY created_at DESC,id LIMIT ? OFFSET ?',(self.auth.settings.env,limit,offset))]
        items=[]
        with self.auth.tx() as cx:
            for row in rows:
                owner=cx.execute('SELECT a.phone FROM accounts a JOIN account_workspaces w ON w.account_id=a.id WHERE a.env=? AND w.actor=?',(self.auth.settings.env,row['owner'])).fetchone()
                summary={key:row.get(key) for key in ('id','title','display_name','status','published','moderation_status','moderation_reason','created_at','data_origin')}
                summary.update({'workspace':row['owner'].split(':')[0],'owner_name':owner['phone'][:3]+'****'+owner['phone'][-4:] if owner else '历史 / 合成数据'})
                items.append(summary)
        return {'items':items,'total':total}

    def detail(self, kind, id, user):
        table={'jobs':'job_profiles','resumes':'resumes'}[kind]
        row=self.svc.db.get(table,id)
        if not row:raise DomainError('NOT_FOUND','记录不存在。',404)
        self.record(user,'查看资料',kind,id,'平台工作人员按监管职责查看资料')
        # Dedicated staff permission does not change the ordinary owner-based APIs.
        keys=('id','title','source_jd','status','published','profile','moderation_status','moderation_reason') if kind=='jobs' else ('id','display_name','text','data_origin')
        return {key:row.get(key) for key in keys}

    def account_action(self, id, disabled, data, user):
        reason=self.reason(data)
        with self.auth.tx() as cx:
            account=cx.execute('SELECT * FROM accounts WHERE id=? AND env=?',(id,self.auth.settings.env)).fetchone()
            if not account:raise DomainError('NOT_FOUND','账号不存在。',404)
            if account['role']=='admin':raise DomainError('ADMIN_PROTECTED','不能通过业务监管暂停平台工作人员账号。',403)
            cx.execute('UPDATE accounts SET disabled=? WHERE id=?',(int(disabled),id))
            if disabled:cx.execute('DELETE FROM sessions WHERE account_id=?',(id,))
            self.record(user,'暂停账号' if disabled else '恢复账号','accounts',id,reason,cx)
        return {'message':'账号已暂停，全部旧会话已失效。' if disabled else '账号已恢复，可以重新登录。'}

    def job_action(self, id, suspended, data, user):
        reason=self.reason(data)
        with self.svc.db.transaction() as cx:
            cx.execute('BEGIN IMMEDIATE')
            job=self.svc.db.get('job_profiles',id,cx)
            if not job or not job['owner'].startswith('enterprise:'):raise DomainError('NOT_FOUND','招聘岗位不存在。',404)
            result=self.svc.db.update('job_profiles',id,{'published':False,'moderation_status':'suspended' if suspended else 'cleared','moderation_reason':reason},cx)
            self.svc.db.audit('平台下架岗位' if suspended else '平台解除岗位限制',{'job_id':id,'reason':reason,'staff_id':user['id']},user['actor'],cx=cx)
        self.record(user,'下架岗位' if suspended else '解除岗位限制','jobs',id,reason)
        return {'id':result['id'],'published':False,'moderation_status':result['moderation_status']}

    def events(self, offset, limit):
        with self.auth.tx() as cx:
            args=(self.auth.settings.env,)
            total=cx.execute('SELECT COUNT(*) FROM platform_admin_events e JOIN accounts a ON a.id=e.staff_id WHERE a.env=?',args).fetchone()[0]
            rows=cx.execute('SELECT e.* FROM platform_admin_events e JOIN accounts a ON a.id=e.staff_id WHERE a.env=? ORDER BY e.created_at DESC,e.id LIMIT ? OFFSET ?',(*args,limit,offset)).fetchall()
        return {'items':[dict(row) for row in rows],'total':total}

    def governance_jobs(self, offset, limit, query, user):
        filters="env=? AND owner LIKE 'enterprise:%'"
        params=[self.auth.settings.env]
        if query.strip():
            filters+=" AND instr(lower(json_extract(payload,'$.title')),lower(?))>0";params.append(query.strip())
        with self.svc.db.transaction() as cx:
            total=cx.execute('SELECT COUNT(*) FROM job_profiles WHERE '+filters,params).fetchone()[0]
            rows=[self.svc.db.decode(r) for r in cx.execute('SELECT * FROM job_profiles WHERE '+filters+' ORDER BY created_at DESC,id LIMIT ? OFFSET ?',[*params,limit,offset])]
        self.record(user,'查看治理岗位','governance-jobs','page','按平台监管职责选择企业岗位')
        return {'items':[{k:r.get(k) for k in ('id','title','owner','status','version')} for r in rows],'total':total}

    def governance_audit(self, offset, limit, user):
        with self.svc.db.transaction() as cx:
            totals=cx.execute("""SELECT COUNT(*),COALESCE(SUM(json_extract(payload,'$.detail.cost_cny')),0),
                SUM(json_extract(payload,'$.result')='告警') FROM audit_logs WHERE env=?""",(self.auth.settings.env,)).fetchone()
            rows=[self.svc.db.decode(r) for r in cx.execute('SELECT * FROM audit_logs WHERE env=? ORDER BY created_at DESC,id LIMIT ? OFFSET ?', (self.auth.settings.env,limit,offset))]
        # Platform audit is metadata only: no prompt, resume, raw provider response or keys.
        fields={'agent','model_id','model','model_label','provider','protocol','prompt_version','duration_seconds','usage','cost_cny',
                'price_configured','failure_code','failure_stage','provider_status','provider_error_code','job_id','report_id','resume_id',
                'application_id','profile_version','version','dimension_version','engine_version','action','skipped'}
        logs=[{**{k:r[k] for k in ('id','owner','created_at','event_type','result')},'detail':{k:v for k,v in r['detail'].items() if k in fields}} for r in rows]
        self.record(user,'查看跨账号审计','governance-audit','page','按平台监管职责查看调用及操作元数据')
        return {'logs':logs,'total':totals[0],'cost_cny':round(totals[1],6),'alerts':totals[2] or 0,'model_mode':self.svc.settings.llm_mode}

    def governance_memory(self, job_id, user):
        job=self.svc.db.get('job_profiles',job_id)
        if not job or not job['owner'].startswith('enterprise:'): raise DomainError('NOT_FOUND','企业岗位不存在。',404)
        self.record(user,'查看校准记忆','jobs',job_id,'按平台监管职责查看指定岗位的校准记录')
        return self.svc.db.list('calibration_memory',owner=job['owner'],job_id=job_id)

    def governance_quality(self, job_id, user):
        job=self.svc.db.get('job_profiles',job_id)
        if not job or not job['owner'].startswith('enterprise:'): raise DomainError('NOT_FOUND','企业岗位不存在。',404)
        self.record(user,'查看岗位质量统计','jobs',job_id,'按平台监管职责查看聚合统计')
        return self.svc.quality_summary(job_id,job['owner'])

    def governance_job_action(self, id, operation, data, user):
        self.svc.writable()
        job=self.svc.db.get('job_profiles',id)
        if not job or not job['owner'].startswith('enterprise:'): raise DomainError('NOT_FOUND','企业岗位不存在。',404)
        reason=self.reason(data)
        self.record(user,'治理操作：'+operation,'jobs',id,reason)
        actor=job['owner']
        if operation=='benchmark': return self.svc.build_benchmark(id,actor)
        if operation=='resume':
            self.svc.db.audit('分析恢复',{'job_id':id,'staff_id':user['id'],'reason':reason},actor)
            return {'message':'已记录平台工作人员恢复该岗位分析。'}
        reports=self.svc.db.list('ability_reports',owner=actor,job_id=id)
        anchors={}
        for r in reports:
            if r['status']=='已确认': anchors.setdefault(r['resume_id'],r)
        if len(anchors)<10: return {'skipped':True,'message':'指定岗位锚定样本不足十份，未调用模型。'}
        counts={};totals={}
        token=current_actor.set(actor)
        try:
            for r in list(anchors.values())[:20]:
                resume=self.svc.owned('resumes',r['resume_id'],actor)
                evaluated=self.svc.evaluate(job,resume,actor)
                for d in r['dimensions']:
                    newer=next((v for v in evaluated['dimensions'] if v['dimension_id']==d['dimension_id']),None)
                    key=d['dimension_id'];totals[key]=totals.get(key,0)+1
                    counts[key]=counts.get(key,0)+int(not newer or (newer['tier'],newer.get('tier_range',[]))!=(d['tier'],d.get('tier_range',[])))
        finally: current_actor.reset(token)
        rates={key:counts[key]/count for key,count in totals.items()}
        self.svc.db.audit('漂移监控',{'job_id':id,'rates':rates,'staff_id':user['id'],'reason':reason},actor,'告警' if any(rate>.2 for rate in rates.values()) else '正常')
        return {'rates':rates,'skipped':False}

    def governance_memory_action(self, id, action, data, user):
        self.svc.writable();reason=self.reason(data)
        row=self.svc.db.get('calibration_memory',id)
        if not row or not row['owner'].startswith('enterprise:'): raise DomainError('NOT_FOUND','校准记录不存在。',404)
        self.record(user,'校准记忆：'+action,'calibration-memory',id,reason)
        from .db import now
        return self.svc.db.update('calibration_memory',id,{'confirmed':True} if action=='confirm' else {'deleted_at':now()})
