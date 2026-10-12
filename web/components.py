import html
import json
import streamlit as st
from web.client import get
from app.deterministic import rationale_for_display, presentation_violations


def h(value): return html.escape(str(value),quote=True)


def block(markup): st.html(markup)


def header(title,subtitle,eyebrow="工作台"):
    block(f'<div class="page-heading"><div class="eyebrow">{h(eyebrow)}</div><h1>{h(title)}</h1><p>{h(subtitle)}</p></div>')


def badge(text,kind="neutral"):
    return f'<span class="badge {h(kind)}">{h(text)}</span>'


def empty(title,description):
    block(f'<div class="empty-state"><div class="empty-mark">＋</div><h3>{h(title)}</h3><p>{h(description)}</p></div>')


def notice(footer=False):
    cfg=get("/config/presentation",quiet=True)
    if cfg:
        block(f'<div class="{"result-footer" if footer else "bias-notice"}"><span class="notice-dot"></span>{h(cfg["footer"] if footer else cfg["bias_notice"])}</div>')


def job_selector(key="job", confirmed=False):
    rows=get("/jobs") or []
    if confirmed: rows=[r for r in rows if r["status"]=="已确认"]
    if not rows:
        empty("先添加一个岗位","粘贴岗位描述并确认画像，之后就可以填写偏好、分析简历。")
        return None
    ids=[r["id"] for r in rows]
    current=st.session_state.get("selected_job")
    index=ids.index(current) if current in ids else len(ids)-1
    selected=st.selectbox("当前岗位",ids,index=index,format_func=lambda id:next(r["title"] for r in rows if r["id"]==id),key=key)
    st.session_state.selected_job=selected
    return next(r for r in rows if r["id"]==selected)


def resume_selector(key="resume"):
    rows=get("/resumes") or []
    if not rows:
        empty("先导入一份简历","在「我的简历」添加文字或上传文件，然后回来进行对照。")
        return None
    selected=st.selectbox("选择简历",[r["id"] for r in rows],format_func=lambda id:next(r["display_name"] for r in rows if r["id"]==id),key=key)
    return next(r for r in rows if r["id"]==selected)


def relation(tier, candidate=False, job=""):
    cfg=get("/config/presentation",quiet=True)
    label=cfg["tier_labels"].get(tier,"证据不足") if cfg else "证据不足"
    if candidate and tier!="insufficient": return f"{tier} · {label}（相对 {job}）"
    return label


def mode_caption(row):
    label="本地演示规则" if row.get("mode")=="demo" else "DeepSeek AI 分析"
    st.caption(f"{label} · 合成数据" if row.get("data_origin")=="synthetic" else label+" · 用户导入数据")


def report_view(report,candidate=False):
    notice()
    cfg = get('/config/presentation', quiet=True)
    if not cfg:
        st.info('结果加载中，请稍后重试')
        return
    visible_text = [report['display_name'], report['job_title']]
    for d in report['dimensions']:
        visible_text.extend([d['name'], rationale_for_display(d['rationale'], cfg, candidate, report['job_title']), *d['evidence']])
    for skill in report['skill_levels']:
        visible_text.extend([skill['skill'], skill['requirement_quote'], *skill['evidence']])
    if any(presentation_violations(value, cfg, enterprise=not candidate) for value in visible_text):
        st.info('结果加载中，请稍后重试')
        notice(True)
        return
    mode_caption(report)
    rubric=report.get("rubric_snapshot",{})
    if rubric.get("status")!="已冻结": st.caption('本次判据：' + rubric.get('version', '历史版本') + ' · ' + rubric.get('status', '未冻结') + '；结果用于流程与证据对照。')
    block(f'<div class="report-summary"><div>{badge(report.get("status","对照结果"),"purple")} {badge("建议人工复核" if report["confidence"]=="low" else "文本依据已整理")}<h2>{h(report["display_name"])} <span>与 {h(report["job_title"])}</span></h2><p>从具体经历出发，了解相符之处、现有差距与尚未描述的方面。</p></div></div>')
    sections=[("strengths","相符与优势","green"),("weaknesses","现有差距","amber"),("insufficient","待了解的方面","neutral")]
    cols=st.columns(3)
    for col,(key,title,color) in zip(cols,sections):
        items=report["structure_view"][key]
        with col:
            block(f'<div class="structure {color}"><div class="section-kicker">{h(title)}</div>'+(''.join(f'<div class="structure-item"><strong>{h(d["name"])}</strong><span>{h(relation("insufficient" if key=="insufficient" else d["tier"],candidate,report["job_title"]))}</span></div>' for d in items) or '<p>当前没有此类记录</p>')+'</div>')
    st.subheader("逐项查看依据")
    for d in sorted(report["dimensions"],key=lambda d:(d["priority"],d["dimension_id"])):
        with st.expander(d["name"]+" · "+relation(d["tier"],candidate,report["job_title"]),expanded=True):
            st.write(rationale_for_display(d['rationale'], cfg, candidate, report['job_title']))
            if d.get("tier_range"):
                st.caption("证据支持的关系范围："+" — ".join(relation(t,candidate,report["job_title"]) for t in d["tier_range"]))
                if d.get('cross_band_reason'): st.caption(rationale_for_display(d['cross_band_reason'], cfg, candidate, report['job_title']))
            for quote in d["evidence"]: block(f'<div class="quote"><span>简历原文</span><p>{h(quote)}</p></div>')
            if not d["evidence"]: st.caption("现有文本没有足够依据，暂不作判断。")
    st.subheader("技能与岗位要求")
    for s in report["skill_levels"]:
        with st.expander(s["skill"]+" · "+relation(s["tier"],candidate,report["job_title"])):
            st.write(f"岗位要求：{s['required_level']} 级行为判据；简历描述支持：{s['evidence_level']} 级行为判据。")
            block(f'<div class="quote"><span>岗位原文</span><p>{h(s["requirement_quote"])}</p></div>')
            for quote in s["evidence"]: block(f'<div class="quote"><span>简历原文</span><p>{h(quote)}</p></div>')
            for hit in s.get('anchor_hits', []):
                st.caption('命中特征：' + hit['feature'])
            if s["evidence_level"]==0: st.caption("无可用证据。未描述不代表不会。")
    if not candidate:
        with st.expander(f"面试准备 · {len(report.get('open_questions',[]))} 个待了解方面",expanded=False):
            for q in report.get("open_questions",[]):
                st.markdown(f"**{q['item']}**")
                st.write(q["hint"])
            if not report.get("open_questions"): st.write("当前没有待验证项，可开展常规面试。")
            for q in report.get("followups",[]): st.write(q["question"])
    if candidate:
        with st.expander("岗位要求的可评估性提示"):
            diagnosis=report.get("diagnosis",{})
            for f in diagnosis.get("findings",[]):
                st.write(f["type"]+"："+f["statement"])
                st.caption("岗位原文："+f["jd_quote"])
            if not diagnosis.get("findings"): st.write("未发现可确定的问题。")
            if not diagnosis.get("benchmark_available"): st.caption("当前缺少同类岗位基准，尚未进行这一类比较。")
        with st.expander("量规差距说明"):
            for item in report.get("gap_explanations",[]):
                st.markdown(f"**{item['skill']}**")
                st.write("量规原文 · 岗位要求的行为："+item["requirement"])
                st.write("量规原文 · 现有描述支持的行为："+item["evidence_anchor"])
            if not report.get("gap_explanations"): st.write("当前未发现证据层面的缺口。")
    with st.expander("版本与比较依据"):
        st.write("排序依次比较相符及以上的维度、优先级顺序中的逐维关系，以及证据充分程度。区间使用较保守的一侧；完全相同则并列。")
        st.caption(f"画像版本 {report['profile_version']} · 判据 {report['rubric_version']} · 优先级 {report['priority_version']} · 模型 {report['model_version']}")
    notice(footer=True)
