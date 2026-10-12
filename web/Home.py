import sys
import base64
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import streamlit as st
from web.client import get
from web.components import block
from web.pages import *

st.set_page_config(page_title="同频 · 人才发掘 Agent 系统",page_icon=str(ROOT/"web"/"logo.svg"),layout="wide",initial_sidebar_state="expanded")
st.html('<style>'+ (ROOT/"web"/"styles.css").read_text(encoding="utf-8")+'</style>')
st.session_state["_config_cache"]={}
if "actor" not in st.session_state:st.session_state.actor="enterprise:demo"
with st.sidebar:
    encoded=base64.b64encode((ROOT/"web"/"logo.svg").read_bytes()).decode()
    block('<div class="brand"><img alt="同频" src="data:image/svg+xml;base64,'+encoded+'"><div><strong>同频</strong><small>TALENT DISCOVERY</small></div></div>')
    role=st.selectbox("当前视角",["enterprise","candidate"],format_func=lambda s:"企业工作台" if s=="enterprise" else "求职者视角",key="role")
    if role=="candidate":
        people=get("/demo/people",quiet=True) or []
        if people:
            current=st.selectbox("演示身份",[p["actor"] for p in people],format_func=lambda id:next(p["name"] for p in people if p["actor"]==id))
        else:current="candidate:local"
    else:current="enterprise:demo"
    if current!=st.session_state.actor:
        st.session_state.actor=current
        st.session_state.pop("selected_job",None)
        st.session_state.pop("selected_match",None)
        st.rerun()
    health=get("/health",quiet=True)
    if health:st.caption("本地演示规则 · 合成示例" if health["llm_mode"]=="demo" else "DeepSeek AI 模式")
    else:st.warning("后端服务未连接")

def page(func,title,path,icon,default=False):return st.Page(func,title=title,url_path=path,icon=f":material/{icon}:",default=default)
if role=="enterprise":
    nav={
      "智能双选":[page(matches_page,"匹配建议","matches","join_inner",True),page(preferences_page,"企业偏好与氛围","preferences","tune")],
      "招聘工作台":[page(jobs_page,"岗位管理","jobs","work_outline"),page(profile_page,"岗位画像确认","profile","fact_check"),page(requirements_page,"需求澄清与诊断","requirements","forum"),page(resumes_page,"简历批次与初筛","resumes","folder_open"),page(reports_page,"能力报告","reports","description"),page(ranking_page,"候选人比较","ranking","view_column")],
      "治理":[page(audit_page,"审计中心","audit","shield"),page(config_page,"配置中心","config","settings"),page(selfcheck_page,"标准自检 · 内部","selfcheck","science")]
    }
else:
    nav={
      "智能双选":[page(matches_page,"匹配建议","matches","join_inner",True),page(preferences_page,"我的偏好","preferences","tune")],
      "求职者工作台":[page(resumes_page,"我的简历","resumes","folder_open"),page(fit_page,"岗位对照分析","fit","difference"),page(compare_page,"岗位对照排序","compare","view_column"),page(benchmark_page,"岗位参考基准","benchmark","bar_chart")]
    }
pg=st.navigation(nav,position="hidden")
with st.sidebar:
    for group,links in nav.items():
        st.caption(group)
        for item in links:st.page_link(item)
    block('<div class="sidebar-note">每一条结论，都应有依据。<br>每一次选择，都由双方决定。<br><br>演示视角用于展示流程，尚未接入正式登录。<br>人才发掘 Agent 系统 · 0.1</div>')
if not health:
    header("后端服务尚未启动","运行启动脚本后，刷新页面即可连接。")
    st.code("python start.py",language="powershell")
else:pg.run()
