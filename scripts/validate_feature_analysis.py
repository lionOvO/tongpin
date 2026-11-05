"""Statically validate the feature documents and render every Mermaid twice.

Uses isolated dependencies already installed for render_development_docs.py.
Never imports the application, reads credentials/business DBs, or contacts APIs.
"""
import ast
import functools
import hashlib
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / '功能业务分析'
ART = ROOT / 'artifacts/feature-analysis'
BLOCK = re.compile(r'```mermaid\r?\n([\s\S]*?)```')


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def static_checks(manifest):
    diagrams = []
    links = 0
    errors = []
    actual_docs = {str(p.relative_to(DOCS)).replace('\\', '/') for p in DOCS.glob('*/*.md') if p.name != 'README.md'}
    if actual_docs != set(manifest['documents']):
        errors.append('Document files differ from manifest')
    for relative, digest in manifest['documents'].items():
        path = DOCS / relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            errors.append('Changed document: ' + relative)
        source = path.read_text(encoding='utf-8')
        blocks = BLOCK.findall(source)
        if len(blocks) != 2 or not blocks[0].startswith('flowchart TB') or not blocks[1].startswith('sequenceDiagram'):
            errors.append('Expected one flowchart and one sequence: ' + relative)
        for index, code in enumerate(blocks):
            diagrams.append({'document': relative, 'kind': 'flowchart' if index == 0 else 'sequence', 'code': code})
    for path in DOCS.rglob('*.md'):
        for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
            links += 1
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc:
                continue
            file = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
            if file == DOCS / '校验记录.md':
                continue  # Written below after all actual results are known.
            if not file.exists():
                errors.append(f'Broken link in {path.name}: {target}')
            elif re.fullmatch(r'L\d+', parsed.fragment):
                if int(parsed.fragment[1:]) > len(file.read_text(encoding='utf-8').splitlines()):
                    errors.append(f'Invalid source line in {path.name}: {target}')
    routes = set()
    for node in ast.walk(ast.parse((ROOT / 'app/main.py').read_text(encoding='utf-8'))):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in node.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and isinstance(d.func.value, ast.Name) and d.func.value.id == 'api'
                    and d.func.attr in {'get', 'post', 'put', 'delete', 'patch', 'head', 'options'}
                    and d.args and isinstance(d.args[0], ast.Constant)):
                routes.add(d.func.attr.upper() + ' ' + d.args[0].value)
    if routes != set(manifest['coverage']):
        errors.append('Current routes differ from coverage inventory')
    for route, docs in manifest['coverage'].items():
        if not docs or any(p not in manifest['documents'] for p in docs):
            errors.append('Uncovered route: ' + route)
        if not any(f'`{route}`' in (DOCS / p).read_text(encoding='utf-8') for p in docs):
            errors.append('Route absent from linked docs: ' + route)
    if len(diagrams) != manifest['diagrams']:
        errors.append('Incorrect total diagram count')
    if errors:
        raise ValueError('\n'.join(errors))
    return diagrams, links, len(routes)


def render_all(diagrams):
    from playwright.sync_api import sync_playwright
    packages = [('10.6.1', 'mermaid-typora'), ('11.17.2', 'mermaid')]
    deps = ROOT / 'artifacts/development-docs/tools/node_modules'
    for version, package in packages:
        actual = json.loads((deps / package / 'package.json').read_text(encoding='utf-8'))['version']
        if version != actual:
            raise ValueError(f'Expected Mermaid {version}; found {actual}')
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    edge = next((str(p) for p in [Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'),
                    Path('C:/Program Files/Microsoft/Edge/Application/msedge.exe')] if p.exists()), None)
    selected = [0, 1, 80, 81, 150, 151, 176, 177]
    results = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, **({'executable_path': edge} if edge else {}))
            context = browser.new_context(viewport={'width': 1500, 'height': 1000}, reduced_motion='reduce')
            context.route('**/*', lambda r: r.continue_() if r.request.url.startswith(origin + '/') or r.request.url.startswith('data:') else r.abort())
            for version, package in packages:
                page = context.new_page()
                page.goto(origin + '/README.md')
                page.evaluate('''async ({url}) => {
                    const {default:mermaid} = await import(url);
                    window.mm=mermaid;
                    mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'base',
                        flowchart:{htmlLabels:true,useMaxWidth:false},
                        sequence:{useMaxWidth:false,wrap:true,width:180}});
                    document.body.innerHTML='<div id="preview"></div>';
                    document.body.style.cssText='margin:20px;background:white;font-family:Microsoft YaHei,sans-serif';
                }''', {'url': origin + f'/artifacts/development-docs/tools/node_modules/{package}/dist/mermaid.esm.min.mjs'})
                records = []
                for start in range(0, len(diagrams), 8):
                    batch = [{'index': i, **diagrams[i]} for i in range(start, min(start + 8, len(diagrams)))]
                    rendered = page.evaluate('''async ({batch,selected}) => {
                        const results=[];
                        for (const d of batch) {
                            try {
                                await mm.parse(d.code);
                                const {svg}=await mm.render('feature-'+d.index,d.code);
                                if (!svg.includes('<svg') || svg.includes('Syntax error in text')) throw new Error('Invalid SVG');
                                document.getElementById('preview').innerHTML=svg;
                                const el=document.querySelector('#preview svg');
                                const bounds=el.getBBox();
                                if (!(bounds.width>0 && bounds.height>0)) throw new Error('Empty diagram');
                                results.push({index:d.index,document:d.document,kind:d.kind,parsed:true,rendered:true,
                                    width:Math.ceil(bounds.width),height:Math.ceil(bounds.height),
                                    ...(selected.includes(d.index)?{svg}: {})});
                            } catch(e) { results.push({index:d.index,document:d.document,kind:d.kind,error:String(e)}); }
                            document.getElementById('preview').innerHTML='';
                            for (const el of document.querySelectorAll('body > div:not(#preview)')) el.remove();
                        }
                        return results;
                    }''', {'batch': batch, 'selected': selected if version == '10.6.1' else []})
                    for record in rendered:
                        svg = record.pop('svg', None)
                        if svg:
                            stem = f'{record["index"]:03}-{record["kind"]}'
                            (ART / (stem + '.svg')).write_text(svg, encoding='utf-8')
                            page.evaluate('''svg => {
                                document.getElementById('preview').innerHTML=svg;
                                const el=document.querySelector('#preview svg');
                                el.style.maxWidth='1440px';el.style.height='auto';
                            }''', svg)
                            page.locator('#preview svg').screenshot(path=str(ART / (stem + '.png')), timeout=30000)
                            page.evaluate("document.getElementById('preview').innerHTML=''")
                        records.append(record)
                    if start % 40 == 0:
                        print(f'Mermaid {version}: {min(start+8,len(diagrams))}/{len(diagrams)}', flush=True)
                results[version] = records
                page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    return results


def main():
    manifest = json.loads((ART / 'manifest.json').read_text(encoding='utf-8'))
    diagrams, links, routes = static_checks(manifest)
    results = render_all(diagrams)
    failures = [(version, record) for version, records in results.items() for record in records if 'error' in record]
    report = {'checked_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
              'document_baseline': manifest['date'], 'features': manifest['features'],
              'diagrams_per_engine': len(diagrams), 'local_links': links, 'routes': routes,
              'status': 'passed' if not failures else 'failed', 'failures': len(failures),
              'source_sha256': hashlib.sha256((ROOT / 'app/main.py').read_bytes()).hexdigest(),
              'documents': manifest['documents'], 'engines': results}
    (ART / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = '\n'.join(f'| Mermaid {v} | {len(rs)} | {sum(r.get("rendered",False) for r in rs)} | {sum("error" in r for r in rs)} |' for v,rs in results.items())
    (DOCS / '校验记录.md').write_text(f'''# 功能业务分析校验记录

[返回总目录](README.md)

文档业务基线：{manifest['date']}。本记录来自实际静态检查与本地浏览器渲染；完整机器结果见 [validation.json](../artifacts/feature-analysis/validation.json)。

## 范围与结果

- {manifest['modules']} 个模块、{manifest['features']} 个独立功能文件；每篇恰好一张业务流程图和一张时序图，共 {len(diagrams)} 张。
- 当前 `app/main.py` 的 {routes} 个 HTTP 方法/路径全部在接口覆盖索引中有文档映射；这是静态覆盖，不代表所有接口已做运行测试。
- 检查 {links} 个本地 Markdown 链接，包括模块导航、需求来源、代码文件及引用行号；未发现失效文件或越界行号。
- 按生成清单逐篇校验 SHA-256，文件集合、数量与清单一致。

| 引擎 | 尝试图数 | 成功渲染 SVG | 失败 |
| --- | --- | --- | --- |
{rows}

状态：**{'通过' if not failures else '存在错误，需修复后重跑'}**。Mermaid 10.6.1 对应截图中 Typora 使用的版本；同时检查 11.17.2。全部图均执行 parse、render 和 SVG 非空尺寸检查，代表性图另保存 SVG/PNG 于 `artifacts/feature-analysis/`，用于人工查看布局。

## 复现与维护

在项目根目录运行：

```powershell
& '.\\.venv\\Scripts\\python.exe' 'scripts/build_feature_analysis.py'
& '.\\.venv\\Scripts\\python.exe' 'scripts/validate_feature_analysis.py'
```

渲染脚本复用开发文档工具目录中的固定 Mermaid 版本和现有 Playwright、Edge；依赖安装方法见 `scripts/render_development_docs.py` 文件头。仅启动临时本地静态文件服务器，浏览器禁止访问外部地址。

本次未启动或导入业务应用、未读取真实数据库与 `.env`、未调用模型或短信服务、未执行投递及清理操作；不将文档校验表述为生产业务验收。代码或功能变更后应重新核对业务追踪并运行上述两步。
''', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'documents','engines'}}, ensure_ascii=False), flush=True)
    if failures:
        print(json.dumps(failures, ensure_ascii=False), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
