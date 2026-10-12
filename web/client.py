import os
import requests
import streamlit as st

BASE=os.getenv("API_BASE_URL","http://127.0.0.1:8000").rstrip("/")


def request(method,path,data=None,quiet=False,raw=False,files=None):
    try:
        response=requests.request(method,BASE+path,headers={"X-Demo-Actor":st.session_state.get("actor","enterprise:demo")},json=data if files is None else None,files=files,timeout=180)
        if response.status_code>=400:
            try: message=response.json()["detail"]["message"]
            except (ValueError,KeyError,TypeError): message=f"请求失败（{response.status_code}），请稍后重试"
            if not quiet: st.error(message)
            return None
        return response.content if raw else response.json()
    except requests.RequestException:
        if not quiet: st.error("服务暂时无法连接。请先启动后端，再刷新页面。")
        return None


def get(path,**kwargs):
    cache=st.session_state.get("_config_cache",{})
    if path.startswith("/config/") and not kwargs.get("raw"):
        if path not in cache:cache[path]=request("GET",path,**kwargs)
        return cache[path]
    return request("GET",path,**kwargs)
def post(path,data=None,**kwargs): return request("POST",path,data,**kwargs)
def put(path,data=None,**kwargs): return request("PUT",path,data,**kwargs)
