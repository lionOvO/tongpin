"""Build the development handbook's route index, SVG diagrams and offline HTML.

Prerequisites (run from the repository root):
  npm install --prefix artifacts/development-docs/tools --no-fund --no-audit --ignore-scripts mermaid@11.17.2 marked@16.4.2 mermaid-typora@npm:mermaid@10.6.1
  .venv/Scripts/python.exe scripts/render_development_docs.py

Uses the existing dev dependency Playwright with local Edge/Chrome, or its
installed Chromium. It never imports the application or reads .env / data.
All HTTP requests are confined to a temporary loopback static server.
Every diagram must also parse and render with Mermaid 10.6.1 (Typora compatibility).
"""
import argparse
import ast
import functools
import hashlib
import html
import json
import re
import threading
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/同频项目开发文档.md'
ARTIFACTS = ROOT / 'artifacts/development-docs'
ASSETS = ROOT / 'docs/assets/development'
METHODS = {'get', 'post', 'put', 'delete', 'patch', 'options', 'head'}


def routes():
    result = []
    for node in ast.walk(ast.parse((ROOT / 'app/main.py').read_text(encoding='utf-8'))):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        annotations = [ast.unparse(a.annotation) for a in node.args.args if a.annotation]
        scope = next((a for a in annotations if a in {'Actor', 'Admin', 'Candidate', 'Recruiter', 'HiringActor'}), 'Request')
        for decorator in node.decorator_list:
            if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == 'api'
                    and decorator.func.attr in METHODS and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)):
                continue
            path = decorator.args[0].value
            if not any(a == 'Request' for a in annotations) and scope == 'Request':
                scope = '公开'
            result.append({'method': decorator.func.attr.upper(), 'path': path, 'scope': scope,
                           'handler': node.name, 'line': node.lineno})
    return sorted(result, key=lambda r: (r['path'], r['method']))


def update_index():
    inventory = routes()
    rows = ['| 方法 | 后端路径 | 首层依赖 | 处理函数（main.py） |', '| --- | --- | --- | --- |']
    rows += [f"| {r['method']} | `{r['path']}` | {r['scope']} | `{r['handler']}`（L{r['line']}） |" for r in inventory]
    text = DOC.read_text(encoding='utf-8')
    text = re.sub(r'<!-- API_INDEX_START -->.*?<!-- API_INDEX_END -->',
                  '<!-- API_INDEX_START -->\n\n' + '\n'.join(rows) + '\n\n<!-- API_INDEX_END -->', text, flags=re.S)
    DOC.write_text(text, encoding='utf-8')
    return inventory


def check_links(source):
    anchors = set(re.findall(r'<a id="([^"]+)"', source))
    missing = []
    for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', source):
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            continue
        if parsed.path and not (DOC.parent / unquote(parsed.path)).exists():
            missing.append(target)
        elif not parsed.path and parsed.fragment and unquote(parsed.fragment) not in anchors:
            missing.append(target)
    if missing:
        raise ValueError('Unresolved links: ' + ', '.join(missing))
    return len(re.findall(r'\[[^\]]+\]\(([^)]+)\)', source))


CSS = '''
:root{--ink:#17243a;--muted:#4c5a70;--brand:#534ab7;--line:#d6deec;--soft:#f0f4fa}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:28px}
body{margin:0;color:var(--ink);background:#edf2f9;font:15px/1.85 "Segoe UI","Microsoft YaHei",sans-serif}
a{color:#4c3eae;text-decoration:none}a:hover{text-decoration:underline}a:focus-visible,summary:focus-visible{outline:3px solid #9c90ec;outline-offset:3px}
aside{position:fixed;inset:0 auto 0 0;width:270px;padding:32px 22px;background:#292344;color:#eeeaff;overflow:auto}
.brand{font-size:26px;font-weight:750;letter-spacing:.1em;color:white}.brand small{display:block;font-size:10px;letter-spacing:.25em;color:#bbb2ef}
.side-note{font-size:12px;color:#c1bbd6;line-height:1.7;margin:20px 0 26px}nav a{display:block;font-size:13px;padding:8px 10px;color:#eeebff;border-radius:7px;line-height:1.6}nav a:hover{background:#443a65;text-decoration:none}
.nav-heading{font-size:11px;text-transform:uppercase;letter-spacing:.16em;color:#afa6cd;margin:24px 10px 10px}
.mobile-nav{display:none}main{margin-left:270px;padding:36px 40px 64px;max-width:1580px}
header{background:linear-gradient(120deg,#292344,#51448e);color:white;border-radius:18px;padding:36px 40px;margin-bottom:28px}
header .eyebrow{font-size:11px;letter-spacing:.18em;color:#d3caff}header h1{font-size:32px;line-height:1.4;margin:10px 0 12px}header p{font-size:14px;max-width:820px;color:#e5dff6;margin:0}
.pills{display:flex;gap:10px;flex-wrap:wrap;margin-top:22px}.pills span{border:1px solid #8f83b5;padding:3px 11px;border-radius:20px;font-size:11px}
article{background:white;border:1px solid var(--line);border-radius:16px;padding:28px 38px 48px;box-shadow:0 4px 18px #24345b06;min-width:0}
article>h1{font-size:26px;margin-top:0}h2{font-size:24px;line-height:1.5;padding-top:22px;margin:38px 0 20px;border-top:2px solid #d9d4f2}
h3{font-size:18px;line-height:1.6;margin:28px 0 12px}p{margin:12px 0}li{margin:6px 0}strong{color:#17243a}blockquote{border-left:4px solid #8370d6;background:#f4f1fc;padding:10px 18px;margin:16px 0;color:var(--muted)}
.table-wrap{overflow-x:auto;margin:18px 0 26px;border:1px solid var(--line);border-radius:9px}
table{border-collapse:collapse;width:100%;min-width:650px;font-size:13px;line-height:1.75}th{background:#e9e6f6;text-align:left;font-weight:650;color:#322761}th,td{padding:12px 14px;border-bottom:1px solid #e0e6f0;vertical-align:top}tr:nth-child(even) td{background:#f8fafd}tr:last-child td{border-bottom:0}
pre{background:#202a3d;color:#edf1fb;padding:18px 20px;border-radius:9px;overflow:auto;font:12px/1.8 Consolas,"Microsoft YaHei",monospace;tab-size:4}
:not(pre)>code{font-size:.89em;background:#f0eef8;padding:2px 5px;border-radius:4px;color:#4b3b83;overflow-wrap:anywhere}
figure{margin:22px 0 30px;padding:22px 18px 12px;border:1px solid #d4dceb;border-radius:12px;background:#fbfcff}
.diagram-scroll{overflow-x:auto;text-align:center}.diagram-scroll svg{max-width:100%;height:auto}figcaption{font-size:12px;color:var(--muted);margin-top:12px;padding-top:10px;border-top:1px solid #e3e7f0}figure details{font-size:12px;color:var(--muted);margin-top:8px}summary{cursor:pointer}
.footer{color:var(--muted);font-size:12px;padding:24px 4px}.read-nav{background:#f6f8fc;border:1px solid var(--line);border-radius:10px;padding:12px 20px}
@media(max-width:1100px){aside{width:230px;padding:24px 14px}main{margin-left:230px;padding:24px}article{padding:24px}header{padding:28px}}
@media(max-width:760px){aside{display:none}main{margin:0;padding:14px}header{padding:24px 20px;border-radius:12px}header h1{font-size:26px}article{padding:20px 16px;border-radius:12px}h2{font-size:21px}h3{font-size:17px}.mobile-nav{display:block;background:white;border:1px solid var(--line);border-radius:9px;padding:10px 16px;margin-bottom:16px}.mobile-nav nav a{color:var(--brand)}.mobile-nav nav a:hover{background:#eeeafb}body{font-size:14px}figure{padding:12px 6px}.diagram-scroll svg{max-width:none;min-width:520px;width:100%}table{font-size:12px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media print{@page{size:A4;margin:16mm 13mm}body{background:white;font-size:10pt}aside,.mobile-nav,.footer{display:none}main{margin:0;padding:0;max-width:none}header{padding:20px;background:#eeeafa;color:#272041;break-after:avoid}header .eyebrow,header p{color:#4c4562}article{border:0;border-radius:0;padding:0;box-shadow:none}h2,h3{break-after:avoid}h2{font-size:18pt;margin-top:24pt}h3{font-size:13pt}.table-wrap{overflow:visible}table{min-width:0;font-size:8pt}th,td{padding:6pt;overflow-wrap:anywhere}pre{white-space:pre-wrap;font-size:8pt}figure{break-inside:avoid;padding:8pt}figure details{display:none}.diagram-scroll{overflow:visible}.diagram-scroll svg{max-width:100%;min-width:0}a{color:inherit}}
'''


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def build(edge=None):
    inventory = update_index()
    source = DOC.read_text(encoding='utf-8')
    modules = ARTIFACTS / 'tools/node_modules'
    for package in ('mermaid/dist/mermaid.esm.min.mjs', 'marked/lib/marked.esm.js',
                    'mermaid-typora/dist/mermaid.esm.min.mjs'):
        if not (modules / package).exists():
            raise SystemExit('Missing isolated build dependencies. See this script docstring / --help.')
    from playwright.sync_api import sync_playwright
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    bundle = origin + '/artifacts/development-docs/tools/node_modules/'
    executable = edge
    if not executable:
        executable = next((p for p in (
            'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
            'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
            'C:/Program Files/Google/Chrome/Application/chrome.exe') if Path(p).exists()), None)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') or route.request.url.startswith('data:') else route.abort())
            page = context.new_page()
            page.goto(origin + '/README.md')
            # Use a separate page to avoid sharing Mermaid internals between versions.
            compatibility_page = context.new_page()
            compatibility_page.goto(origin + '/README.md')
            compatibility = compatibility_page.evaluate('''async ({source,bundle}) => {
                const {default:mermaid} = await import(bundle+'mermaid-typora/dist/mermaid.esm.min.mjs');
                mermaid.initialize({startOnLoad:false,securityLevel:'strict'});
                const blocks=[...source.matchAll(/```mermaid\\r?\\n([\\s\\S]*?)```/g)];
                if (!blocks.length) throw new Error('No Mermaid diagrams found');
                const results=[];
                for (let i=0;i<blocks.length;i++) {
                    try {
                        await mermaid.parse(blocks[i][1]);
                        const {svg}=await mermaid.render('compat-diagram-'+(i+1),blocks[i][1]);
                        if (!svg.includes('<svg') || svg.includes('Syntax error in text')) {
                            throw new Error('Invalid SVG output');
                        }
                        results.push({number:i+1,parsed:true,rendered:true});
                    } catch(error) {
                        throw new Error('Mermaid 10.6.1 compatibility failed for diagram '+(i+1)+': '+error);
                    }
                }
                return results;
            }''', {'source':source,'bundle':bundle})
            compatibility_page.close()
            compiled = page.evaluate('''async ({source,bundle}) => {
                const {marked} = await import(bundle+'marked/lib/marked.esm.js');
                const {default:mermaid} = await import(bundle+'mermaid/dist/mermaid.esm.min.mjs');
                mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'base',fontFamily:'Microsoft YaHei, Segoe UI, sans-serif',
                  themeVariables:{primaryColor:'#ece7fc',primaryTextColor:'#17243a',primaryBorderColor:'#8877c9',lineColor:'#697695',secondaryColor:'#e7f3f3',tertiaryColor:'#f3f6fb',fontSize:'15px'},
                  flowchart:{htmlLabels:false,curve:'basis'},sequence:{useMaxWidth:true,wrap:true}});
                const diagrams=[]; const blocks=[...source.matchAll(/```mermaid\\r?\\n([\\s\\S]*?)```/g)];
                let markdown=source;
                for (let i=0;i<blocks.length;i++) {
                    await mermaid.parse(blocks[i][1]);
                    const {svg}=await mermaid.render('diagram-'+(i+1),blocks[i][1]);
                    diagrams.push({number:i+1,source:blocks[i][1],svg});
                    markdown=markdown.replace(blocks[i][0],'<div data-diagram="'+(i+1)+'"></div>');
                }
                return {html:marked.parse(markdown),diagrams};
            }''', {'source': source, 'bundle': bundle})
            content = compiled['html']
            for diagram in compiled['diagrams']:
                number = diagram['number']
                (ASSETS / f'diagram-{number:02}.svg').write_text(diagram['svg'], encoding='utf-8')
                figure = (f'<figure id="figure-{number}"><div class="diagram-scroll">{diagram["svg"]}</div>'
                          f'<figcaption>图 {number} · 当前实现结构与流程</figcaption>'
                          f'<details><summary>查看 Mermaid 源码</summary><pre>{html.escape(diagram["source"])}</pre></details></figure>')
                content = content.replace(f'<div data-diagram="{number}"></div>', figure)
            content = content.replace('<table>', '<div class="table-wrap"><table>').replace('</table>', '</table></div>')
            # Rewrite in-document anchors unchanged; repository source links remain relative.
            navigation = ''.join(f'<a href="#{key}">{html.escape(title)}</a>'
                                 for title, key in re.findall(r'\d+\. \[([^\]]+)\]\(#([^)]+)\)', source))
            document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>同频 · 项目开发文档</title><style>{CSS}</style></head><body>
<aside><div class="brand">同频<small>TONGPIN / ENGINEERING</small></div><p class="side-note">基于项目代码与 PRD 的开发手册<br>核对日期 2026-10-16 · v1.0</p><div class="nav-heading">CONTENTS / 文档导航</div><nav aria-label="章节导航">{navigation}</nav></aside>
<main><header><div class="eyebrow">DEVELOPMENT HANDBOOK / 01</div><h1>让选择有据可循。</h1><p>同频项目开发文档：从双向选择业务，到授权快照、证据型 AI、开发测试与运行维护。</p><div class="pills"><span>Vue + FastAPI</span><span>业务 / 架构 / 时序</span><span>内嵌 SVG · 离线阅读</span></div></header><details class="mobile-nav"><summary>展开章节导航</summary><nav>{navigation}</nav></details><article>{content}</article><div class="footer">图表已内嵌，无需在线图表服务。Markdown 为维护源；接口索引由 app/main.py 静态提取。可使用浏览器打印。</div></main></body></html>'''
            target = DOC.with_suffix('.html')
            target.write_text(document, encoding='utf-8')
            link_count = check_links(source)
            page.goto(origin + '/docs/' + target.name)
            page.wait_for_load_state('networkidle')
            page.screenshot(path=str(ARTIFACTS / 'handbook-desktop.png'))
            metrics = []
            for width, height in ((1440,1000),(1024,768),(390,844)):
                page.set_viewport_size({'width':width,'height':height})
                metrics.append(page.evaluate('''() => ({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
                    diagrams:document.querySelectorAll('figure svg').length,tableCount:document.querySelectorAll('table').length,
                    placeholders:document.querySelectorAll('[data-diagram]').length,
                    emptyDiagrams:[...document.querySelectorAll('figure svg')].filter(s=>s.getBoundingClientRect().height<20).length})'''))
                if width == 390:
                    page.screenshot(path=str(ARTIFACTS / 'handbook-mobile.png'))
            page.set_viewport_size({'width':1440,'height':1000})
            page.locator('#figure-4').scroll_into_view_if_needed()
            page.screenshot(path=str(ARTIFACTS / 'handbook-architecture.png'))
            page.locator('#figure-7').scroll_into_view_if_needed()
            page.screenshot(path=str(ARTIFACTS / 'handbook-sequence.png'))
            page.locator('#figure-5').screenshot(path=str(ARTIFACTS / 'handbook-entities.png'))
            if any(m['scrollWidth'] > m['width'] or m['emptyDiagrams'] or m['placeholders'] for m in metrics):
                raise ValueError('HTML layout validation failed: ' + json.dumps(metrics))
            evidence = {'checked_at':datetime.now().isoformat(timespec='seconds'), 'routes':len(inventory),
                'diagrams':len(compiled['diagrams']),'markdown_links':link_count,'viewports':metrics,
                'source_sha256':hashlib.sha256(DOC.read_bytes()).hexdigest(),
                'tools':{p:json.loads((modules/p/'package.json').read_text(encoding='utf-8'))['version'] for p in ('mermaid','marked','mermaid-typora')},
                'typora_mermaid_compatibility':compatibility,
                'application_imported':False,'business_tests_executed':False,'external_model_calls':False}
            (ARTIFACTS/'validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
            browser.close()
            print(json.dumps(evidence,ensure_ascii=False))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--index-only', action='store_true', help='Refresh route index without browser rendering')
    parser.add_argument('--browser', help='Path to a local Edge/Chrome executable')
    args = parser.parse_args()
    if args.index_only:
        print(f'Indexed {len(update_index())} routes')
    else:
        build(args.browser)
