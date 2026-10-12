"""Start the local API and UI; Ctrl+C stops the processes started here."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv
import webbrowser

ROOT=Path(__file__).resolve().parent


def ensure_environment(install=False):
    python=ROOT/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.exists():
        print('正在创建 Python 虚拟环境……',flush=True)
        venv.EnvBuilder(with_pip=True).create(ROOT/'.venv');install=True
    probe=subprocess.run([str(python),'-c','import fastapi, uvicorn, streamlit, httpx, multipart, pypdf, dotenv'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if install or probe.returncode:
        print('正在安装依赖，首次启动需要联网，请稍候……',flush=True)
        subprocess.run([str(python),'-m','pip','install','-r',str(ROOT/'requirements-lock.txt')],check=True,cwd=ROOT)
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


def main():
    parser=argparse.ArgumentParser(description='同频：一键启动前后端')
    parser.add_argument('--install',action='store_true',help='安装或更新锁定依赖')
    parser.add_argument('--open-browser',action='store_true',help='就绪后打开前端')
    parser.add_argument('--api-port',type=int,help='固定后端端口；省略时从 8000 自动寻找空闲端口')
    parser.add_argument('--web-port',type=int,help='固定前端端口；省略时从 8501 自动寻找空闲端口')
    args=parser.parse_args()
    runtime=ROOT/'data'/'runtime';runtime.mkdir(parents=True,exist_ok=True)
    children=[];handles=[]
    try:
        args.api_port,args.web_port=select_ports(args.api_port,args.web_port)
        python=ensure_environment(args.install)
        check_ports(args.api_port,args.web_port)
        api_url=f'http://127.0.0.1:{args.api_port}'
        web_url=f'http://127.0.0.1:{args.web_port}'
        environment={**os.environ,'API_BASE_URL':api_url,'PYTHONUNBUFFERED':'1','PYTHONUTF8':'1'}
        services=[('api',args.api_port,['-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(args.api_port)],'/health'),('web',args.web_port,['-m','streamlit','run','web/Home.py','--server.address=127.0.0.1',f'--server.port={args.web_port}','--server.headless=true'],'/_stcore/health')]
        for name,port,command,health in services:
            print(f'正在启动 {"后端" if name=="api" else "前端"}……',flush=True)
            log=(runtime/f'{name}.log').open('a',encoding='utf-8');handles.append(log)
            process=subprocess.Popen([str(python),*command],cwd=ROOT,env=environment,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            children.append(process)
            wait_ready(process,f'http://127.0.0.1:{port}{health}',runtime/f'{name}.log')
        print(f'启动成功！\n前端：{web_url}\n后端接口文档：{api_url}/docs',flush=True)
        print(f'日志目录：{runtime}\n请保留本窗口，按 Ctrl+C 停止前后端。',flush=True)
        if args.open_browser:
            try:webbrowser.open(web_url)
            except webbrowser.Error:print('无法自动打开浏览器，请手动访问上述前端地址。',flush=True)
        while all(p.poll() is None for p in children):time.sleep(0.5)
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
