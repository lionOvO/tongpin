# 参与同频开发

欢迎提交问题、文档改进与 Pull Request。请先阅读 [README](README.md) 和相关功能说明，再围绕一个具体问题提交改动。

## 开发环境

使用 Python 3.13、Node.js 22.13 或更高的受支持 LTS 版本。从自己的 Fork 创建分支：

```bash
git clone https://github.com/你的用户名/tongpin.git
cd tongpin
git switch -c feat/your-change
python start.py --install
```

后端默认位于 `127.0.0.1:8000`，前端默认位于 `127.0.0.1:8501`，地址以启动输出为准。前端代理目标由 `VITE_API_PROXY_TARGET` 设置；API 密钥与短信密钥只保存在本地 `.env`。

## 验证改动

```bash
# Windows；其他系统使用 .venv/bin/python
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest -q --basetemp=./artifacts/pytest-local
```

```bash
cd frontend
npm ci
npm test
npm run build
```

先运行与改动相关的测试；接口、授权或数据结构变动应补充有意义的回归用例。界面变动应检查桌面、手机、键盘焦点和系统“减少动态效果”设置。

## 隔离交互预览

`tests/serve_material_agent_preview.py` 使用合成账号、随机验证码测试传输、临时数据库和脚本化 AI。运行前安装上面的开发依赖，不需要真实短信或付费模型。它只绑定本机回环地址，不可用于生产或公网登录。

终端一，在仓库根目录运行：

```bash
.venv/Scripts/python.exe tests/serve_material_agent_preview.py
```

终端二，连接它的专用前端代理。PowerShell：

```powershell
cd frontend
$env:VITE_API_PROXY_TARGET='http://127.0.0.1:8027'
npm run dev -- --host 127.0.0.1 --port 8527 --strictPort
```

Bash：

```bash
cd frontend
VITE_API_PROXY_TARGET=http://127.0.0.1:8027 npm run dev -- --host 127.0.0.1 --port 8527 --strictPort
```

访问 `http://127.0.0.1:8527/login`，使用该夹具创建的**仅限测试环境**账号 `13800000981` / `Scenario-password-2026`。进入 AI 工作区发送“请优化项目表达并生成草稿”，可核对工具进度和修改前后对照。这不是线上账号或通用登录密码。

招聘预览入口是 `tests/serve_recruiter_agent_preview.py`，API 为 `8028`；另开前端 `8528` 并将代理目标设为 `8028`。测试账号 `13800000991` / `Scenario-password-2026`，选择“招聘方”登录。夹具中的认证仅用于验证 UI，不代表真实企业通过审核。

预览数据库位于被 Git 忽略的 `artifacts/` 子目录；每次启动独立生成。退出时在各自终端按 Ctrl+C，不影响正常运行的本地服务。响应内容是固定测试数据，不能据此评估模型效果。

## 提交约定

- 一个 PR 解决一个可说明的问题，写清触发场景、修改结果和验证方法。
- 修改 UI 时附合成数据截图；涉及授权时说明角色、归属、投递撤回和隐私开关的行为。
- 保留原始材料与明确确认流程，不让 AI 未经确认覆盖简历，不以缺少描述直接推断个人能力。
- 不提交 `.env`、密钥、真实手机号、简历、数据库、上传文件、运行日志或账号清单。
- 不随意更新锁文件、加入大模型权重或构建产物；依赖变化需说明用途。
- 贡献原创内容；引入外部代码或素材时说明来源并保留许可。

提交前检查 `git diff --check` 与暂存列表。提交即表示你有权提供该贡献，并同意将原创贡献按项目 MIT 许可证发布。

## 问题与安全报告

普通问题请在 [Issues](https://github.com/lionOvO/tongpin/issues) 提供复现步骤、预期与实际结果、环境和已隐藏隐私的截图。涉及越权、账号接管或个人资料泄露时，请使用 [安全报告流程](SECURITY.md)，不要公开利用细节。
