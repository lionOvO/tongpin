import json
import base64
import streamlit as st
from web.client import get,post,put,request
from web.components import *


def matches_page():
    candidate=st.session_state.actor.startswith("candidate:")
    header("智能双选","看见双方的偏好，也看见每一条建议的依据。","同频 / 智能双选")
    emblem='<svg class="pair-emblem" viewBox="0 0 180 86" fill="none" aria-hidden="true"><path d="M42 43H138" stroke="#c3bde7" stroke-width="1.5" stroke-dasharray="4 4"/><rect x="8" y="12" width="62" height="62" rx="20" fill="#ded9f5"/><rect x="108" y="12" width="62" height="62" rx="20" fill="#e2e9f6"/><path d="M26 41h25m-25 8h18m-18-16h14" stroke="#8a7ec5" stroke-width="3" stroke-linecap="round"/><path d="M128 41h23m-23 8h15m-15-16h19" stroke="#8e9fc4" stroke-width="3" stroke-linecap="round"/><circle cx="89" cy="43" r="11" fill="#fff"/><path d="m85 43 3 3 6-7" stroke="#978bcc" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    emblem=emblem.replace('<svg ','<svg xmlns="http://www.w3.org/2000/svg" ',1)
    emblem='<img class="pair-emblem" alt="双方期待相连" src="data:image/svg+xml;base64,'+base64.b64encode(emblem.encode()).decode()+'">'
    block('<div class="welcome"><div><h2>好的相遇，始于彼此理解。</h2><p>把要求与期待放在一起，让选择有据可循。<br>系统提供参考，最终选择属于你们。</p></div>'+emblem+'</div>')
    if candidate:
        resume=resume_selector("match_resume")
        job=job_selector("match_job",confirmed=True)
        if not resume or not job:return
        if st.button("对照双方偏好",type="primary"):
            with st.spinner("正在整理双方填报的依据…"): result=post("/matches/run",{"job_id":job["id"],"resume_id":resume["id"]})
            if result:st.toast("偏好对照已完成")
        rows=[m for m in (get("/matches") or []) if m["job_id"]==job["id"] and m["resume_id"]==resume["id"]]
    else:
        job=job_selector("match_job",confirmed=True)
        if not job:return
        rows=[m for m in (get("/matches") or []) if m["job_id"]==job["id"]]
    latest={}
    for row in rows:latest.setdefault(row["resume_id"],row)
    rows=list(latest.values())
    if not rows:
        notice();empty("双方的偏好还没有放在一起","先完成偏好填写，再发起对照。无法判断也是一种有效结果。")
        if not candidate:
            participants=get("/matches/participants?job_id="+job["id"]) or []
            if participants:
                selected=st.selectbox("已同意参与对照的求职者",[r["id"] for r in participants],format_func=lambda id:next(r["display_name"] for r in participants if r["id"]==id))
                if st.button("开始偏好对照",type="primary"):post("/matches/run",{"job_id":job["id"],"resume_id":selected});st.rerun()
        notice(True);return
    presentation=get('/config/presentation')
    texts=[value for row in rows for value in [row['job_title'],row['candidate_name'],row['ambience_text'],row['basis_statement']]]
    texts.extend(value for row in rows for d in row['dimension_results'] for value in [d['name'],d['ent_quote'],d['cand_quote']])
    if any(presentation_violations(value,presentation,enterprise=not candidate) for value in texts):
        notice();st.info('结果加载中，请稍后重试');notice(True);return
    block('<div class="workspace-label"><h3>'+('我的岗位对照' if candidate else '本次参与对照的求职者')+'</h3><span>依据双方主动填报 · 合成示例明确标注</span></div>')
    labels=get("/config/presentation")["preference_labels"]
    cols=st.columns(min(len(rows),3))
    for i,row in enumerate(rows):
        with cols[i%3]:
            required=[r for r in row["dimension_results"] if r["required"]]
            block(f'<div class="person-card"><div class="person-top"><div class="avatar">{h(row["candidate_name"][0])}</div><div><h3>{h(row["candidate_name"])}</h3><p>{h(row["job_title"])}</p></div></div>{badge(labels[row["overall_tier"]],"green" if row["overall_tier"]=="高" else "purple")}{badge("合成示例" if row["data_origin"]=="synthetic" else "用户填报")}</div>')
            if st.button("查看双方依据",key="select_"+row["id"],width="stretch"):st.session_state.selected_match=row["id"]
    ids=[r["id"] for r in rows]
    current=st.session_state.get("selected_match")
    row=next((r for r in rows if r["id"]==current),rows[0])
    notice()
    left,right=st.columns([2.1,1],gap="large")
    with left:
        with st.container(border=True):
            block('<div class="workspace-label" style="margin-top:0"><h3>双方偏好对照</h3>'+badge("基于已过期填报" if row["outdated"] else "当前填报","amber" if row["outdated"] else "neutral")+'</div>')
            block(f'<div class="bridge"><div class="bridge-panel"><small>企业的期待</small><h3>{h(row["job_title"])}</h3><p>企业主动填写</p></div><div class="bridge-connector">↔</div><div class="bridge-panel"><small>求职者的偏好</small><h3>{h(row["candidate_name"])}</h3><p>求职者主动填写</p></div></div>')
            def render_dim(dim):
                text=dim["tier"]+" · "+labels[dim["tier"]] if candidate else labels[dim["tier"]]
                if candidate:text += "（相对 "+row["job_title"]+"）"
                with st.expander(dim["name"]+" · "+text):
                    a,b=st.columns(2)
                    with a:block(f'<div class="quote"><span>企业填报原文</span><p>{h(dim["ent_quote"])}</p></div>')
                    with b:block(f'<div class="quote"><span>求职者填报原文</span><p>{h(dim["cand_quote"])}</p></div>')
                    if dim["unmatched_reason"]:st.caption(dim["unmatched_reason"])
                    elif dim["distance"] is not None:st.caption("双方选择相同" if dim["distance"]==0 else "双方选择在这一维度存在差异，可在沟通中进一步了解。")
            for dim in row["dimension_results"]:
                if dim["required"]:render_dim(dim)
            with st.expander("更多偏好 · 协作、反馈与节奏"):
                for dim in row["dimension_results"]:
                    if not dim["required"]:render_dim(dim)
            st.caption(row["basis_statement"])
    with right:
        block(f'<div class="context-card"><h3>团队氛围</h3>{badge("企业自行填写")}<p>{h(row["ambience_text"] or "企业暂未填写氛围描述。")}</p><div class="meta">自述与系统对照结果分别呈现</div></div>')
        block('<div class="context-card"><h3>让下一次沟通更具体</h3><div class="step"><span class="step-line">1</span><p>先看双方相符的偏好。</p></div><div class="step"><span class="step-line">2</span><p>展开差异，了解双方填写的原意。</p></div><div class="step"><span class="step-line">3</span><p>对尚未填写的方面，在沟通中继续了解。</p></div></div>')
        st.caption("偏好口径 "+row["dimension_version"]+" · 规则 "+row["engine_version"])
        st.caption("偏好由规则直接对照，不使用 AI 猜测未填写内容。")
    if not candidate:
        with st.expander("重新对照或添加参与者"):
            participants=get("/matches/participants?job_id="+job["id"]) or []
            if participants:
                selected=st.selectbox("求职者",[r["id"] for r in participants],format_func=lambda id:next(r["display_name"] for r in participants if r["id"]==id))
                if st.button("重新对照偏好",type="primary"):
                    if post("/matches/run",{"job_id":job["id"],"resume_id":selected}):st.rerun()
    notice(True)


def preferences_page():
    candidate=st.session_state.actor.startswith("candidate:")
    header("我的偏好" if candidate else "企业偏好与氛围","用三个选择表达主要期待，其他方面可以慢慢补充。","智能双选 / 偏好填写")
    obj=resume_selector("pref_resume") if candidate else job_selector("pref_job",confirmed=True)
    if not obj:return
    cfg=get("/config/preferences")
    history=get("/preferences") or []
    previous=next((p for p in history if p.get("resume_id" if candidate else "job_id")==obj["id"]),{})
    values={}
    with st.form("preferences_"+obj["id"]):
        st.subheader("最在意的三个方面")
        st.caption("三项均须作答，也可以选择「无法判断 / 不愿透露」。")
        def field(dim):
            options=["请选择",*dim["options"],"无法判断 / 不愿透露"]
            old=previous.get("dimensions",{}).get(dim["id"])
            index=options.index(old) if old in options else len(options)-1 if dim["id"] in previous.get("dimensions",{}) else 0
            values[dim["id"]]=st.selectbox(dim["name"],options,index=index,key="pref_"+obj["id"]+dim["id"])
        for d in cfg["dimensions"]:
            if d["required"]:field(d)
        with st.expander("其他偏好 · 可选填"):
            for d in cfg["dimensions"]:
                if not d["required"]:field(d)
        ambience=""
        if not candidate:
            st.subheader("团队氛围")
            st.caption("本内容由企业自行填写。请描述日常协作方式、沟通与工作节奏。")
            ambience=st.text_area("企业自行填写的氛围描述",value=previous.get("ambience_text",""),height=130,max_chars=2000)
        share=st.checkbox("同意将本次偏好用于双方对照，并向本次对照的另一方展示填报依据",value=bool(previous.get("share_with_counterparty")))
        submit=st.form_submit_button("保存偏好",type="primary")
    if submit:
        if any(values[d["id"]]=="请选择" for d in cfg["dimensions"] if d["required"]):st.error("请回答三项主要偏好；允许选择无法判断。")
        else:
            payload={"side":"candidate" if candidate else "enterprise","resume_id" if candidate else "job_id":obj["id"],"dimensions":{k:None if v in {"请选择","无法判断 / 不愿透露"} else v for k,v in values.items()},"dimension_version":cfg["version"],"ambience_text":ambience,"share_with_counterparty":share}
            if post("/preferences/submit",payload):st.success("偏好已保存。历史结果仍使用原填报，重新对照后可查看最新结果。")
    st.caption("偏好口径版本 "+cfg["version"]+" · 每次保存形成独立快照")


def jobs_page():
    header("岗位管理","先明确岗位要什么，再理解双方是否合适。","招聘工作台 / 岗位")
    rows=get("/jobs") or []
    with st.expander("新建岗位 · 粘贴 JD",expanded=not rows):
        with st.form("new_job"):
            title=st.text_input("岗位名称",placeholder="例如：Python 后端工程师")
            jd=st.text_area("岗位描述原文",height=180,placeholder="粘贴岗位职责与任职要求，系统会整理结构化画像。")
            origin=st.selectbox("数据来源",["synthetic","real"],format_func=lambda s:"合成 / 演示数据" if s=="synthetic" else "用户自行导入")
            manual=st.checkbox("手工录入基础画像（不调用 AI）")
            direction=st.selectbox("手工画像的技术方向",["后端开发","前端开发","全栈开发","数据与算法","测试与质量","基础设施"])
            submit=st.form_submit_button("创建并解析岗位",type="primary")
        if submit:
            payload={"title":title,"jd":jd,"data_origin":origin}
            if manual:payload["manual_profile"]={"requirements":[],"direction":direction,"education":None}
            with st.spinner("正在整理岗位描述…"):result=post("/jobs",payload)
            if result:st.session_state.selected_job=result["id"];st.success("岗位已创建，请前往画像确认检查原文依据。")
    for row in rows:
        with st.container(border=True):
            a,b=st.columns([4,1])
            with a:
                st.markdown("**"+row["title"]+"**")
                st.caption(row["profile"]["direction"]+" · 画像 v"+str(row["version"])+" · "+("合成示例" if row["data_origin"]=="synthetic" else "用户导入"))
            with b:st.write(row["status"])
            if st.button("设为当前岗位",key="job_"+row["id"]):st.session_state.selected_job=row["id"];st.toast("当前岗位已切换")


def profile_page():
    header("岗位画像确认","逐条对照原文，确认后再开始简历分析。","招聘工作台 / 画像")
    job=job_selector("profile_job")
    if not job:return
    left,right=st.columns(2,gap="large")
    with left:
        st.subheader("结构化要求")
        direction=st.text_input("技术方向",value=job["profile"]["direction"])
        education=st.selectbox("学历要求",["未指定","大专","本科","硕士","博士"],index=["未指定","大专","本科","硕士","博士"].index(job["profile"].get("education") or "未指定"))
        edited=[]
        for i,req in enumerate(job["profile"]["requirements"]):
            with st.container(border=True):
                a,b=st.columns(2)
                skill=a.text_input("技能",value=req["skill"],key=f"skill_{job['id']}_{job['version']}_{i}")
                level=b.selectbox("要求的行为等级",[1,2,3,4],index=req["required_level"]-1,key=f"level_{job['id']}_{job['version']}_{i}")
                hard=st.checkbox("属于主要要求",value=req["hard"],key=f"hard_{job['id']}_{i}")
                quote=st.text_area("对应岗位原文",value=req["quote"],key=f"quote_{job['id']}_{job['version']}_{i}",height=80)
                edited.append({"skill":skill,"required_level":level,"hard":hard,"quote":quote})
        with st.expander("补充一项技能要求"):
            new_skill=st.text_input("技能名称",key="new_profile_skill")
            new_level=st.selectbox("要求等级",[1,2,3,4],index=1,key="new_profile_level")
            new_quote=st.text_area("从 JD 复制对应原文",key="new_profile_quote")
        if new_skill and new_quote:edited.append({"skill":new_skill,"required_level":new_level,"quote":new_quote,"hard":True})
        if st.button("确认并保存新版本",type="primary"):
            result=put("/jobs/"+job["id"]+"/confirm",{"profile":{"direction":direction,"education":None if education=="未指定" else education,"requirements":edited},"expected_version":job["version"]})
            if result:st.success("画像已确认，后续分析将使用新版本。")
    with right:
        st.subheader("岗位描述原文")
        block('<div class="context-card"><p style="white-space:pre-wrap">'+h(job["source_jd"])+"</p></div>")
        st.caption("修改不会覆盖历史报告；历史报告保留当时的画像快照。")


def resumes_page():
    candidate=st.session_state.actor.startswith("candidate:")
    header("我的简历" if candidate else "简历批次与初筛","原文独立留存，进入分析前隔离个人敏感信息。","求职者 / 简历" if candidate else "招聘工作台 / 简历")
    with st.expander("导入简历",expanded=False):
        uploaded=st.file_uploader("上传 PDF、TXT 或 JSON",type=["pdf","txt","json"],accept_multiple_files=True)
        if st.button("导入所选文件",disabled=not uploaded,help="请先选择文件" if not uploaded else None):
            files=[("files",(f.name,f.getvalue(),f.type)) for f in uploaded]
            with st.spinner("正在解析文件…"):result=request("POST","/resumes/batch",files=files)
            if result:
                st.success(f"已导入 {len(result['resumes'])} 份。")
                for err in result["errors"]:st.error(err["filename"]+"："+err["message"])
        with st.form("resume_text"):
            name=st.text_input("展示名称（演示请使用虚构姓名）")
            text=st.text_area("简历原文",height=180,placeholder="粘贴专业、项目、技能与实践描述。")
            origin=st.selectbox("记录来源",["synthetic","real"],format_func=lambda v:"合成 / 演示数据" if v=="synthetic" else "本人 / 自有简历")
            submit=st.form_submit_button("保存文字简历",type="primary")
        if submit and post("/resumes",{"name":name,"text":text,"data_origin":origin}):st.success("简历已导入。")
    rows=get("/resumes") or []
    if not rows:empty("还没有简历","上传文件或粘贴文字，即可开始。 ");return
    if candidate:
        for r in rows:
            with st.expander(r["display_name"]+" · "+("合成示例" if r["data_origin"]=="synthetic" else "本人导入")):
                st.text(r["text"])
        return
    job=job_selector("batch_job",confirmed=True)
    if not job:return
    if st.button("整理本岗位初筛结果",type="primary"):
        with st.spinner("逐项比对原文与岗位要求…"):post("/batches/run",{"job_id":job["id"]})
    batches=get("/batches?job_id="+job["id"]) or []
    c1,c2,c3,c4=st.columns(4)
    for col,label,value in [(c1,"已导入",len(rows)),(c2,"描述较相符",sum(b["tier"]=="高匹配" for b in batches)),(c3,"有待了解",sum(b["tier"]=="潜力" for b in batches)),(c4,"规则待复核",sum(b["tier"]=="存疑" for b in batches))]:col.metric(label,value)
    selected=st.multiselect("选择需要深入分析的简历",[r["id"] for r in rows],default=[r["id"] for r in rows if any(b["resume_id"]==r["id"] and b["tier"]!="存疑" for b in batches)],format_func=lambda id:next(r["display_name"] for r in rows if r["id"]==id))
    if st.button("生成能力报告",disabled=not selected,help="请先选择简历" if not selected else "按所选数量逐份分析；真实 AI 模式会产生调用费用"):
        with st.spinner("正在逐份整理能力证据，请稍候…"):result=post("/assessments",{"job_id":job["id"],"resume_ids":selected})
        if result:
            st.success(f"已生成 {len(result['reports'])} 份待确认报告。")
            for e in result["errors"]:st.error(e["name"]+"："+e["message"])
    for b in batches:
        with st.expander(b["display_name"]+" · "+("规则未通过" if b["hard_gate_result"]=="规则未通过" else "信息待补充" if b["hard_gate_result"]=="信息待补充" else "描述较相符" if b["tier"]=="高匹配" else "有待了解")):
            for item in b["hits"]+b["misses"]:
                st.markdown("**"+item["skill"]+"** · "+item["reason"])
                for q in item["evidence"]:st.caption("简历原文："+q)
            if b["hard_gate_rule_ids"]:st.caption("规则编号："+"、".join(b["hard_gate_rule_ids"])+"；仅标记供复核，未删除简历。")


def reports_page():
    header("能力报告","先看证据，再作判断。确认后的报告才进入候选人比较。","招聘工作台 / 报告")
    reports=get("/assessments") or []
    if not reports:empty("还没有能力报告","在简历批次选择简历，生成第一份报告。 ");return
    ids=[r["id"] for r in reports]
    if st.session_state.get("review_report") not in ids:st.session_state.pop("review_report",None)
    selected=st.selectbox("选择报告",ids,key="review_report",format_func=lambda id:next(r["display_name"]+" / "+r["job_title"]+" · "+r["status"] for r in reports if r["id"]==id)+" · 分析记录 "+str(len(ids)-ids.index(id)))
    report=next(r for r in reports if r["id"]==selected)
    report_view(report)
    st.subheader("人工审阅")
    if report["status"]=="已打回":
        if st.button("重新生成报告",type="primary"):
            with st.spinner("重新整理证据…"):result=post("/assessments/"+selected+"/rerun")
            if result and result["reports"]:st.rerun()
        return
    with st.container(border=True):
        actions=["确认","单维改档","整份打回"] if report["status"]!="已确认" else ["整份打回"]
        action=st.selectbox("审阅操作",actions,format_func=lambda v:"修改单项关系" if v=="单维改档" else v,key="review_action_"+selected)
        dim=tier=None
        if action=="单维改档":
            dim=st.selectbox("修改的维度",[d["dimension_id"] for d in report["dimensions"]],format_func=lambda id:next(d["name"] for d in report["dimensions"] if d["dimension_id"]==id),key="review_dim_"+selected)
            tiers=get("/config/presentation")["tier_labels"]
            tier=st.selectbox("新的相对要求关系",list(tiers),format_func=lambda t:tiers[t],key="review_tier_"+selected)
        reason=st.text_area("审阅理由（必填）",placeholder="记录本次判断的依据，后续可回溯。",key="review_reason_"+selected)
        confirmed=st.checkbox("整份打回时确认重新分析该报告",key="review_reject_"+selected) if action=="整份打回" else False
        submit=st.button("保存审阅结果",type="primary",key="save_review",disabled=len(reason.strip())<2 or (action=="整份打回" and not confirmed))
    if submit:
        if action=="整份打回" and not confirmed:st.error("请确认整份打回操作。")
        else:
            payload={"report_id":selected,"action":action,"reason":reason}
            if action=="单维改档":payload.update({"dimension_id":dim,"tier_after":tier})
            if post("/reviews",payload):st.rerun()
    if report["status"]=="已确认" and st.button("生成面试追问"):
        if post("/assessments/"+selected+"/followups"):st.rerun()
    with st.expander("审阅记录"):
        for e in get("/reviews?report_id="+selected) or []:
            st.write(("修改单项关系" if e["action"]=="单维改档" else e["action"])+" · "+e["reason"])
            st.caption(e["created_at"])


def ranking_page():
    header("候选人比较","比较的是相对岗位要求的证据，最终判断由人完成。","招聘工作台 / 比较")
    job=job_selector("rank_job",confirmed=True)
    if not job:return
    notice();rows=get("/candidates/ranking?job_id="+job["id"]) or []
    if not rows:empty("还没有已确认的报告","在能力报告中完成审阅与确认，然后回来比较。 ");notice(True);return
    presentation=get('/config/presentation')
    texts=[value for r in rows for value in [r['display_name'],r['job_title']]]
    texts.extend(value for r in rows for d in r['dimensions'] for value in [d['name'],*d['evidence'][:1]])
    if any(presentation_violations(value,presentation) for value in texts):
        st.info('结果加载中，请稍后重试');notice(True);return
    labels=get("/config/presentation")["tier_labels"]
    table=[]
    for r in rows:
        entry={"位次":r["rank"],"姓名":r["display_name"]}
        entry.update({d["name"]:labels[d["tier"]] for d in r["dimensions"]});table.append(entry)
    st.dataframe(table,hide_index=True,width="stretch")
    st.caption("只包含每份简历最新的已确认报告。结果相同则并列，不自动晋级或淘汰。")
    selected=st.multiselect("选择二至四位查看证据",[r["id"] for r in rows],max_selections=4,format_func=lambda id:next(r["display_name"] for r in rows if r["id"]==id))
    if selected:
        cols=st.columns(len(selected))
        for col,id in zip(cols,selected):
            r=next(r for r in rows if r["id"]==id)
            with col:
                st.markdown("**"+r["display_name"]+"**")
                for d in r["dimensions"]:
                    st.write(d["name"]+"："+labels[d["tier"]])
                    for quote in d["evidence"][:1]:st.caption(quote)
    content=get("/candidates/export?job_id="+job["id"],raw=True)
    if content:st.download_button("导出候选人名单",content,file_name="候选人对照.csv",mime="text/csv",type="primary")
    notice(True)


def requirements_page():
    header("需求澄清与 JD 诊断","把岗位的真实需要说清楚，也给要求本身留下讨论空间。","招聘工作台 / 需求")
    job=job_selector("brief_job",confirmed=True)
    if not job:return
    cfg=post("/requirements/clarify",{"job_id":job["id"]})
    if not cfg:return
    with st.form("brief_"+job["id"]):
        answers={q["id"]:st.selectbox(q["question"],q["options"],index=len(q["options"])-1,key=job["id"]+q["id"]) for q in cfg["questions"]}
        submit=st.form_submit_button("保存用人需求",type="primary")
    if submit:
        if post("/requirements/brief",{"job_id":job["id"],"answers":answers}):st.success("需求画像已保存，跳过项将保留为未澄清。")
    briefs=get("/requirements/brief/"+job["id"]) or []
    if briefs:st.dataframe([{ "要求":r["content"],"来源":r["source_tag"],"重要性":r["priority"],"原文":r["jd_quote"]} for r in briefs[0]["requirements"]],hide_index=True,width="stretch")
    if st.button("检查岗位要求"):
        result=post("/requirements/diagnose",{"job_id":job["id"]})
        if result:
            for f in result["findings"]:
                st.info(f["type"]+"："+f["statement"])
                st.caption("岗位原文："+f["jd_quote"])
            if not result["findings"]:st.success("未发现可确定的问题。")
            if not result["benchmark_available"]:st.caption("同类岗位样本不足，未进行超出同级基准这一类诊断。")


def fit_page():
    header("岗位对照分析","了解现有经历与目标岗位的关系，每个结果都保留具体参照。","求职者 / 岗位对照")
    resume=resume_selector("fit_resume")
    if not resume:return
    source=st.radio("岗位来源",["选择已提供岗位","粘贴目标 JD"],horizontal=True)
    payload={"resume_id":resume["id"]}
    job=None
    if source=="选择已提供岗位":
        job=job_selector("fit_job",confirmed=True)
        if not job:return
        payload["job_id"]=job["id"]
    else:
        title=st.text_input("目标岗位名称",value="我的目标岗位")
        jd=st.text_area("目标 JD 原文",height=180)
        payload.update({"title":title,"jd":jd})
    if st.button("开始岗位对照",type="primary"):
        with st.spinner("正在对照经历与岗位要求…"):result=post("/fit/analyze",payload)
        if result:st.session_state.fit_id=result["id"]
    rows=[r for r in (get("/fit/reports") or []) if r["resume_id"]==resume["id"] and (job is None or r["job_id"]==job["id"])]
    if rows:report_view(rows[0],candidate=True)
    else:notice();empty("选择一个具体岗位开始","系统会整理你的经历与这个岗位的关系，并保留原文依据。 ");notice(True)


def compare_page():
    header("岗位对照排序","只比较你提供的岗位，不扩展到其他岗位。","求职者 / 自选岗位")
    resume=resume_selector("compare_resume")
    if not resume:return
    n=st.number_input("本次对照岗位数量",min_value=2,max_value=20,value=3)
    with st.form("compare_form"):
        texts=[st.text_area(f"岗位 {i+1} 的完整 JD",height=130,key=f"compare_jd_{i}") for i in range(n)]
        submit=st.form_submit_button("对照并排序",type="primary")
    if submit:
        if any(len(t.strip())<20 for t in texts):st.error("每份岗位描述至少填写二十个字符。")
        else:
            with st.spinner("正在逐个岗位对照…"):post("/compare/rank",{"resume_id":resume["id"],"job_texts":texts})
    rows=get("/compare/runs") or []
    if rows:
        notice()
        for item in rows[0]["ranked_results"]:
            with st.expander(str(item["rank"])+" · "+item["job_title"],expanded=True):
                st.write(item["basis_statement"])
                for d in item["dimensions"]:st.write(d["name"]+"："+relation(d["tier"],True,item["job_title"]))
        for err in rows[0]["errors"]:st.warning(f"岗位 {err['job_ref']}：{err['error']}")
        notice(True)


def benchmark_page():
    header("岗位参考基准","聚合描述常见要求，只与岗位基准比较。","求职者 / 基准")
    job=job_selector("benchmark_job",confirmed=True)
    if not job:return
    notice();rows=get("/fit/benchmark?job_id="+job["id"],quiet=True)
    if not rows:empty("样本不足，暂不展示基准","同类岗位每项至少有二十份样本时才展示统计。不会提供其他人的画像或排名。")
    else:
        for r in rows:
            with st.container(border=True):
                st.markdown("**"+r["skill"]+"**")
                st.write(f"常见要求：{r['lower_level']} 至 {r['upper_level']} 级行为判据")
                st.caption("合成样例统计，非真实录用数据" if r["source_type"]=="B_synthetic" else "岗位要求推导基准")
    notice(True)


def audit_page():
    header("审计中心","每次调用、人工修正与配置更新都有迹可循。","治理 / 审计")
    result=get("/audit/summary")
    if not result:return
    a,b,c=st.columns(3);a.metric("审计记录",len(result["logs"]));b.metric("待关注告警",result["alerts"]);c.metric("估算 AI 成本",f"¥ {result['cost_cny']:.3f}")
    st.caption("成本按服务器配置的 token 单价估算，价格需要根据实际供应商计费更新。")
    a,b=st.columns(2)
    with a:
        if st.button("检查敏感属性隔离"):
            value=post("/audit/bias-check")
            if value:st.info(value["note"])
    with b:
        if st.button("重跑锚定样本"):
            with st.spinner("检查已确认样本的变化…"):value=post("/audit/drift-check")
            if value:st.info(value.get("message","已完成比较，详细记录已写入审计日志。"))
    logs=[{"时间":r["created_at"][:19].replace("T"," "),"事件":r["event_type"],"结果":r["result"]} for r in result["logs"]]
    st.dataframe(logs,hide_index=True,width="stretch")
    content=get("/audit/export",raw=True)
    if content:st.download_button("导出审计记录",content,"审计记录.md",mime="text/markdown")
    st.subheader("校准记忆")
    for m in get("/memory") or []:
        if m.get("deleted_at"):continue
        with st.container(border=True):
            st.write(m["pattern"]);st.caption("已确认，下次 AI 分析可引用" if m["confirmed"] else "待确认，不会自动注入分析")
            a,b=st.columns(2)
            if a.button("确认这条记忆",key="memoryconfirm"+m["id"],disabled=m["confirmed"]):put("/memory/"+m["id"],{"action":"confirm"});st.rerun()
            if b.button("移除记忆",key="memorydelete"+m["id"]):put("/memory/"+m["id"],{"action":"delete"});st.rerun()
    with st.expander("恢复已暂停的岗位分析"):
        job=job_selector("resume_job",confirmed=True)
        checked=st.checkbox("已检查岗位画像和行为判据")
        if job and st.button("手动恢复分析",disabled=not checked):post("/assessments/resume-job/"+job["id"]);st.success("已记录恢复操作。")


def config_page():
    header("配置中心","两端共用同一份偏好维度、行为判据与呈现规范。","治理 / 配置")
    rubric=get("/config/rubric")
    if rubric:st.info("当前判据："+rubric["version"]+" · "+rubric["status"]+"。新分析使用当前配置；历史报告保留原判据快照。")
    pack=get("/config/packs")
    if pack:st.download_button("导出标准包",json.dumps(pack,ensure_ascii=False,indent=2),"standard-pack.json",mime="application/json")
    uploaded=st.file_uploader("导入标准包",type=["json"],key="pack_file")
    if uploaded and st.button("校验并导入标准包"):
        try:
            if post("/config/packs/import",json.loads(uploaded.getvalue())):st.success("标准包已导入。历史报告保留原配置快照。")
        except ValueError:st.error("文件不是有效 JSON。")
    names={"维度优先级":"priorities","双边偏好维度":"preferences","专业映射":"major-map","行为判据":"rubric","呈现规范":"presentation"}
    label=st.selectbox("选择配置",list(names));name=names[label];value=get("/config/"+name)
    with st.expander("内部配置编辑器",expanded=False):
        st.caption("这是内部维护视图。修改须使用新版本号，保存前服务端会校验。")
        text=st.text_area("配置 JSON",value=json.dumps(value,ensure_ascii=False,indent=2),height=400,key="cfg_"+name)
        if st.button("校验并保存",type="primary"):
            try:
                if put("/config/"+name,json.loads(text)):st.success("新版本已保存；已有分析与对照不会静默重算。")
            except ValueError:st.error("配置不是有效 JSON。")
    with st.expander("演示数据维护"):
        st.caption("只清理当前非生产环境的合成业务数据。先备份，再清理，最后检查引用完整性。")
        health=get("/health") or {}
        confirmation=st.text_input("输入「清理合成数据」确认")
        if st.button("备份并清理",disabled=confirmation!="清理合成数据"):
            result=post("/maintenance/purge",{"env":health.get("env"),"confirmation":confirmation})
            if result:st.success("已完成清理，并保存数据库备份。刷新后可看到空状态。")
        if st.button("重新装载合成示例"):
            if post("/demo/seed"):st.success("示例已装载。")


def selfcheck_page():
    header("标准自检","内部检查输入标准与统计口径，不自动修改量规。","治理 / 内部工具")
    st.info("此页仅提供内部工具。模型准确率与偏见指标须通过独立标注集验证。")
    if st.button("运行规则冒烟检查"):
        result=post("/selfcheck/identifiability")
        if result:st.dataframe(result["fixture_examples"],hide_index=True);st.caption(result["note"])
    job=job_selector("build_benchmark_job",confirmed=True)
    if job and st.button("生成同类岗位基准"):
        result=post("/benchmarks/build",{"job_id":job["id"]})
        if result:st.info(result["message"])
