"""Start the local API and UI; Ctrl+C stops the processes started here."""
import argparse
import os
import shutil
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv
import webbrowser
from html.parser import HTMLParser

ROOT=Path(__file__).resolve().parent


def validate_frontend_entry(folder):
    class EntryParser(HTMLParser):
        mount=False
        module=False

        def handle_starttag(self, tag, attrs):
            attributes=dict(attrs)
            if attributes.get('id')=='app':self.mount=True
            if tag=='script' and attributes.get('type')=='module' and attributes.get('src')=='/src/main.ts':
                self.module=True

    entry=folder/'index.html'
    try:
        parser=EntryParser();parser.feed(entry.read_text(encoding='utf-8'))
        valid=parser.mount and parser.module and (folder/'src'/'main.ts').is_file()
    except (OSError,UnicodeError):valid=False
    if not valid:
        raise RuntimeError(f'前端入口缺失或损坏：{entry}。请恢复 Vue 挂载节点和 /src/main.ts 脚本入口后重试。')


def ensure_frontend(install=False):
    folder=ROOT/'frontend'
    validate_frontend_entry(folder)
    node=shutil.which('node')
    npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
    if not node or not npm:
        raise RuntimeError('Vue 前端需要 Node.js 22 LTS（至少 22.13），请安装并重新打开启动窗口。')
    version=subprocess.check_output([node,'--version'],text=True).strip().lstrip('v')
    parts=tuple(int(p) for p in version.split('.')[:3])
    if parts < (22,13,0):
        raise RuntimeError(f'当前 Node.js {version} 版本过低，请升级至 Node.js 22.13 或更高 LTS 版本。')
    lock=folder/'package-lock.json'
    stamp=folder/'node_modules'/'.tongpin-lock'
    fingerprint=__import__('hashlib').sha256(lock.read_bytes()).hexdigest()
    if install or not (folder/'node_modules'/'vite'/'bin'/'vite.js').exists() or not stamp.exists() or stamp.read_text()!=fingerprint:
        print('正在安装锁定的前端依赖，首次启动需要联网……',flush=True)
        environment={**os.environ,'PATH':str(Path(node).parent)+os.pathsep+os.environ.get('PATH','')}
        try:
            subprocess.run([npm,'ci','--no-fund','--no-audit'],check=True,cwd=folder,env=environment)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError('前端依赖安装失败。Windows 下请先关闭本项目已运行的 Vue 启动窗口，再重试；同时检查网络是否可访问 npm。') from exc
        stamp.write_text(fingerprint)
    return node


def ensure_environment(install=False,legacy=False):
    python=ROOT/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.exists():
        print('正在创建 Python 虚拟环境……',flush=True)
        venv.EnvBuilder(with_pip=True).create(ROOT/'.venv');install=True
    probe=subprocess.run([str(python),'-c','import fastapi, uvicorn, httpx, multipart, pypdf, dotenv, langgraph'+('; import streamlit' if legacy else '')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if install or probe.returncode:
        print('正在安装依赖，首次启动需要联网，请稍候……',flush=True)
        subprocess.run([str(python),'-m','pip','install','-r',str(ROOT/('requirements-lock.txt' if legacy else 'requirements-runtime-lock.txt'))],check=True,cwd=ROOT)
    local=ROOT/'.env'
    if not local.exists():local.write_bytes((ROOT/'.env.example').read_bytes())
    return python


def reserve_port(port):
    # A Windows IPv6 wildcard listener can accept IPv4 while IPv4 bind succeeds.
    with socket.socket() as probe:
        probe.settimeout(0.25)
        if probe.connect_ex(('127.0.0.1',port))==0:
            raise OSError(f'端口 {port} 已有服务监听')
    sock=socket.socket()
    try:
        if os.name=='nt':sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        sock.bind(('127.0.0.1',port))
        return sock
    except OSError:
        sock.close();raise


def check_ports(api_port,web_port):
    if api_port==web_port:raise ValueError('前后端端口不能相同。')
    for port in (api_port,web_port):
        if not 1<=port<=65535:raise ValueError(f'无效端口：{port}')
        try:
            with reserve_port(port):pass
        except OSError as exc:
            raise RuntimeError(f'端口 {port} 已被占用。若本项目已启动，请使用原窗口；否则关闭占用程序，或通过 --api-port / --web-port 指定其他端口。') from exc


def select_ports(api_port=None,web_port=None):
    """Keep explicit ports; find free alternatives for the default ports."""
    if api_port is not None and api_port==web_port:
        raise ValueError('前后端端口不能相同。')
    choices=[('后端',api_port,8000),('前端',web_port,8501)]
    chosen={};reservations=[]
    try:
        # Reserve explicit requests first so automatic choices cannot take them.
        for name,requested,default in sorted(choices,key=lambda item:item[1] is None):
            preferred=default if requested is None else requested
            if not 1<=preferred<=65535:raise ValueError(f'无效端口：{preferred}')
            candidates=range(preferred,min(preferred+100,65536)) if requested is None else [preferred]
            for port in candidates:
                try:sock=reserve_port(port)
                except OSError:continue
                reservations.append(sock);chosen[name]=port
                if port!=preferred:
                    print(f'{name}默认端口 {preferred} 不可用，自动改用 {port}。',flush=True)
                break
            else:
                if requested is not None:
                    raise RuntimeError(f'指定的{name}端口 {requested} 已被占用。请更换指定端口，或不传端口参数以自动选择。')
                raise RuntimeError(f'{name}在 {preferred} 起的 100 个端口内没有可用端口，请通过端口参数指定其他范围。')
        return chosen['后端'],chosen['前端']
    finally:
        for sock in reservations:sock.close()


def wait_ready(process,url,log_path,timeout=60):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if process.poll() is not None:raise RuntimeError(f'服务启动失败，日志：{log_path}')
        try:
            with urllib.request.urlopen(url,timeout=1) as response:
                if response.status==200:return
        except (OSError,urllib.error.URLError):pass
        time.sleep(0.25)
    raise RuntimeError(f'服务启动超时，日志：{log_path}')


def stop_process(process):
    if process.poll() is not None:return
    # Windows venv Python may spawn another interpreter; stop this entire tree.
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    else:process.terminate()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill();process.wait()


def build_api_command(python, port, reload=True):
    command = [str(python), '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)]
    if reload:
        # Vite already reloads frontend code. Keep the local API in sync, too.
        # Watch only app code, not private uploads, databases or test artifacts.
        command.extend(['--reload', '--reload-dir', str(ROOT / 'app')])
    return command


def api_source_stamp():
    return tuple(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in (ROOT / 'app').rglob('*.py')))


def main():
    parser=argparse.ArgumentParser(description='同频：一键启动前后端')
    parser.add_argument('--install',action='store_true',help='安装或更新锁定依赖')
    parser.add_argument('--open-browser',action='store_true',help='就绪后打开前端')
    parser.add_argument('--api-port',type=int,help='固定后端端口；省略时从 8000 自动寻找空闲端口')
    parser.add_argument('--web-port',type=int,help='固定前端端口；省略时从 8501 自动寻找空闲端口')
    parser.add_argument('--no-api-reload',action='store_true',help='关闭本地后端代码自动重载')
    parser.add_argument('--legacy-streamlit',action='store_true',help='旧界面已归档；当前登录只支持 Vue 前端')
    args=parser.parse_args()
    if args.legacy_streamlit:
        parser.error('旧 Streamlit 界面使用演示身份，不能连接新的账号认证。请直接运行 python start.py 使用 Vue 登录页。')
    runtime=ROOT/'data'/'runtime';runtime.mkdir(parents=True,exist_ok=True)
    children=[];handles=[]
    try:
        args.api_port,args.web_port=select_ports(args.api_port,args.web_port)
        python=ensure_environment(args.install,args.legacy_streamlit)
        node=None if args.legacy_streamlit else ensure_frontend(args.install)
        check_ports(args.api_port,args.web_port)
        api_url=f'http://127.0.0.1:{args.api_port}'
        web_url=f'http://127.0.0.1:{args.web_port}'
        environment={**os.environ,'API_BASE_URL':api_url,'VITE_API_PROXY_TARGET':api_url,'PYTHONUNBUFFERED':'1','PYTHONUTF8':'1'}
        # Uvicorn's Windows reload uses a console Ctrl+C event. Hidden services
        # have no console, so that signal never stops the old worker. Supervise
        # the owned API process tree here instead of hanging on that signal.
        supervise_reload=os.name=='nt' and not args.no_api_reload
        api_command=build_api_command(python,args.api_port,reload=not args.no_api_reload and not supervise_reload)
        source_stamp=api_source_stamp()
        web_command=([str(python),'-m','streamlit','run','web/Home.py','--server.address=127.0.0.1',f'--server.port={args.web_port}','--server.headless=true'] if args.legacy_streamlit else [node,str(ROOT/'frontend'/'node_modules'/'vite'/'bin'/'vite.js'),'--host','127.0.0.1','--port',str(args.web_port)])
        services=[('api',args.api_port,api_command,'/health',ROOT),('web',args.web_port,web_command,'/_stcore/health' if args.legacy_streamlit else '/',ROOT if args.legacy_streamlit else ROOT/'frontend')]
        for name,port,command,health,folder in services:
            print(f'正在启动 {"后端" if name=="api" else "前端"}……',flush=True)
            log=(runtime/f'{name}.log').open('a',encoding='utf-8');handles.append(log)
            process=subprocess.Popen(command,cwd=folder,env=environment,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            children.append(process)
            wait_ready(process,f'http://127.0.0.1:{port}{health}',runtime/f'{name}.log')
        print(f'启动成功！\n前端：{web_url}\n后端接口文档：{api_url}/docs',flush=True)
        if not args.no_api_reload:print('后端代码自动重载已开启；修改 app 代码后会自动更新接口。',flush=True)
        print(f'日志目录：{runtime}\n请保留本窗口，按 Ctrl+C 停止前后端。',flush=True)
        if args.open_browser:
            try:webbrowser.open(web_url)
            except webbrowser.Error:print('无法自动打开浏览器，请手动访问上述前端地址。',flush=True)
        while all(p.poll() is None for p in children):
            time.sleep(0.5)
            if supervise_reload:
                updated=api_source_stamp()
                if updated!=source_stamp:
                    print('后端代码已变化，正在重新加载……',flush=True)
                    stop_process(children[0])
                    children[0]=subprocess.Popen(api_command,cwd=ROOT,env=environment,stdout=handles[0],stderr=handles[0],creationflags=subprocess.CREATE_NO_WINDOW)
                    wait_ready(children[0],api_url+'/health',runtime/'api.log')
                    source_stamp=updated
                    print('后端已更新。',flush=True)
        raise RuntimeError(f'服务意外退出，请查看日志：{runtime}')
    except KeyboardInterrupt:
        print('\n正在停止前后端……',flush=True)
        return 0
    except (OSError,RuntimeError,ValueError,subprocess.CalledProcessError) as exc:
        print(f'启动失败：{exc}',file=sys.stderr,flush=True)
        return 1
    finally:
        for process in reversed(children):stop_process(process)
        for handle in handles:handle.close()


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
