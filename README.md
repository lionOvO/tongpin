# 同频 · 人才发掘 Agent 系统

完整开发说明见 [同频项目开发文档](docs/同频项目开发文档.md)，涵盖业务、技术架构、数据授权、AI 实现、问题修复与运行维护；也可打开 [HTML 阅读版](docs/同频项目开发文档.html) 查看已渲染的架构图、流程图和时序图。

基于 PRD、SRS 与 UI 文档实现的双边偏好匹配原型。默认前端为独立的 Vue 3 + TypeScript + Vite 页面，后端为 Python 3.13 + FastAPI + Pydantic，业务数据持久化到 SQLite 的业务表。技术用途与本次验证见 [技术与重构说明](docs/前端重构与技术说明.md)。已接入验证码注册、密码／验证码登录、设置／找回密码与真实账号数据隔离，配置见 [登录与账号隔离](docs/登录与账号隔离.md)。

## 本地启动（Windows）

双击项目根目录的 **`一键启动.bat`**。需安装 Python 3.13，以及 Node.js 22.13 或更高的受支持 LTS 版本（原 PDF 预览依赖）。脚本优先使用项目虚拟环境；缺少依赖时安装锁定的 Python 与 npm 依赖，前后端就绪后自动打开浏览器。首次安装需要联网。

保留启动窗口，按 **Ctrl+C** 同时停止本次启动的前后端。默认端口被占用时自动寻找空闲端口，前端自动连接本次后端，浏览器打开实际前端地址；运行地址以窗口输出为准。错误日志在 `data/runtime`。

也可在项目目录运行：

```powershell
python start.py --install
```

后续启动直接运行 `python start.py`。脚本启动两个服务，优先使用以下地址；端口被占用时自动调整：

- 前端：http://127.0.0.1:8501
- 后端接口文档：http://127.0.0.1:8000/docs

启动终端按 Ctrl+C 会关闭本次启动的两个服务。日志在 `data/runtime`。

自定义固定端口并自动打开浏览器（指定端口被占用时明确报错）：

```powershell
.\一键启动.bat --api-port 8003 --web-port 8503
```

也可手工在两个终端运行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd frontend
npm ci
$env:VITE_API_PROXY_TARGET="http://127.0.0.1:8000"
npm run dev -- --port 8501
```

前端通过同源 `/api` 代理连接本次启动的后端，不把 AI 密钥打包进浏览器。旧 Streamlit 页面作为源码参考归档，其演示身份客户端不支持新认证；默认启动和 Docker 部署均使用 Vue，旧启动参数会明确提示不再支持。更新前端依赖前应先关闭已运行的 Vue 启动窗口，避免 Windows 锁定原生构建模块。

## 已提供的流程

- 认证企业公开岗位、求职者明确授权后投递、企业发出沟通邀请、求职者接受或婉拒、站内沟通与共同进展。入口和资料授权规则见 [投递与双向选择](docs/投递与双向选择.md)。
- 招聘端个人资料卡与经历结构视图：按授权投递整理技术经历、业务关联及面试追问，保留原文依据，不自动评分或淘汰。入口及验证方式见 [招聘个人资料卡](docs/招聘个人资料卡.md)。
- 双方消息中心：按投递分开会话，支持邀请回应、文字聊天、未读提醒、历史搜索及可收起的授权资料栏。入口及同步规则见 [消息中心](docs/消息中心.md)。
- 独立求职者 AI 工作区：简历检查、岗位语义对照、自由对话与追问、本人补充确认、草稿前后对照、确认后保存新版本。详见 [AI 工作区](docs/AI工作区.md)。
- 独立招聘 AI 工作区：材料 Agent 基于当前授权投递读取并定位经历、讨论技术与业务关联、准备面试追问，支持流式回答、停止和人工选择保存提纲，保留各投递对话历史，默认 DeepSeek 官方模型。详见 [招聘 AI 工作区](docs/招聘AI工作区.md)及[招聘 Agent 第三阶段](docs/招聘Agent第三阶段.md)。

- 企业偏好与求职者偏好、双方原文对照、无法判断态、历史快照与过期标记。
- 岗位创建、结构化画像编辑与版本确认、需求澄清与三类 JD 诊断。
- PDF/DOC/DOCX/JSON/TXT 批量导入、解析失败隔离、初筛标记、逐维能力报告与技能行为证据。
- 人工确认、关系修正、打回、三次连续打回暂停、校准记忆确认与删除。
- 仅确认报告参与候选人比较、并列排序、默认无联系方式的 CSV 导出。
- 求职者本人岗位对照、粘贴 JD、自选岗位集合排序、量规差距说明。
- 聚合岗位基准及样本不足拦截、审计、成本估算、隔离检查、锚定样本漂移检查。
- 版本化配置、标准包导入导出、清理合成数据、数据库备份与引用检查。

新注册账号从独立空白空间开始，不自动继承旧演示材料。旧数据保留，可通过本机工具显式迁移；管理员可为自己的账号装载私有合成示例。能力报告仍须人工确认后才会参与比较。

## AI 与演示模式

默认 `LLM_MODE=demo`，使用可复现的本地文本规则，无需密钥。界面明确显示「本地演示规则」。这是联调与演示模式，不宣称模型准确率。

真实模型调用在 `.env` 配置：

```dotenv
LLM_MODE=deepseek
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

求职者 AI 工作区支持按任务选择 DeepSeek 和中转 GPT，历史结果保留生成模型。配置与扩展方式见 [模型选择与切换](docs/模型选择与切换.md)。

重启后，JD 与能力证据整理会调用模型；偏好匹配、成绩换算、技能汇总与排序仍由确定性代码执行。每次模型调用记录输入哈希、prompt 版本、时长、token 和估算费用。结构化输出失败重试一次，失败不保存半成品报告。费用单价在 `.env` 配置，示例值不是当前官方报价。

## 本地向量检索（可选）

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-vector.txt
```

预下载 `BAAI/bge-m3` 和 `BAAI/bge-reranker-base`，设置 `VECTOR_ENABLED=true`，重启。使用 SentenceTransformer 做向量编码，CrossEncoder 做重排；索引 metadata 隔离 owner、env 和来源。大模型权重需额外磁盘与内存。默认主流程无需这些依赖。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=./artifacts/pytest-local
cd frontend
npm run test
npm run build
```

Vue 重构及本次登录调整的验证记录分别见技术说明与登录说明。旧 scripts/browser_check.py 及 tests/browser_alignment_check.py 使用已归档的演示身份，不用于验证默认 Vue 页面或新登录接口。

独立人工标注集可用 `scripts/evaluate.py` 计算一致率、证据覆盖、重复一致性和 baseline 差值；格式和实测限制见 [评测说明](docs/evaluation.md)。此前量规对齐验收见 [验证记录](docs/verification.md)，本次重构见 [技术与验证说明](docs/前端重构与技术说明.md)。

## Docker / 腾讯云

正式服务器部署使用独立的 `docker-compose.server.yml` 和 `sh deploy-server.sh`，由宿主机代理连接内部 web；当前按用户要求提供 HTTP :18082；实际服务、环境配置、备份与回滚见 [服务器部署](docs/服务器部署.md)。下方为原有本机 Docker 运行方式，不作为公网生产登录入口。

```bash
cp .env.example .env
chmod 600 .env
docker compose up --build -d --wait
```

默认只映射回环地址，腾讯云演示可用 `ssh -L 8501:127.0.0.1:8501 用户@服务器` 后访问本机 8501。`deploy.sh` 在升级前暂停写入并备份数据卷。业务与可编辑配置均在持久化卷。可选向量版使用 `WITH_VECTORS=true` 构建并预下载模型。

业务接口已要求真实手机号会话，X-Demo-Actor 不再参与授权；APP_ENV=prod 默认使用 HTTPS Secure Cookie；当前 HTTP 部署通过显式 SESSION_COOKIE_SECURE=false 使用独立的 HTTP 会话 Cookie，详见服务器部署文档。已按用户要求从餐小助复制完整短信配置到根目录 .env，沿用默认方案。首页右上角提供账号登录及注册入口：首次需验证码注册并设置密码，之后可密码登录；之前快捷注册的账号从「设置／找回密码」补设密码，保留原账号材料。实际短信送达需使用本人手机验证；不要把密钥粘贴到聊天或提交代码。详细配置、隔离范围、管理员设定、旧数据迁移与部署限制见 [登录与账号隔离](docs/登录与账号隔离.md)。

## 项目结构

```text
app/            API、服务、Agent、确定性规则与 SQLite
frontend/       Vue 3 页面、TypeScript、CSS、接口客户端与前端测试
web/            迁移对照用的旧 Streamlit 页面
config/         默认版本化判据、偏好维度与措辞
tests/          规则与 API 业务验收
scripts/        浏览器验证与辅助工具
docs/           实现口径和验收记录
docker/         两个服务的 Dockerfile
data/           运行数据、原文、配置修订和备份（不入库）
```

完整 PRD 与上游量规已在 docs/upstream 提供并对齐。当前判据状态为「上游已对齐、未冻结」；真实模型效果和完整基准指标需要人工标注集实测，不以自动化测试冒充模型评测。


### 平台工作人员管理端

访问 `http://127.0.0.1:8501/admin/login`。管理端提供企业认证审核、账号监管、招聘岗位下架、简历原文监管及操作记录；普通用户无法登录或自行取得管理权限。未认证企业不能进入招聘空间。工作人员先完成手机号验证注册，再由服务器维护者指定为管理员；具体操作与隔离规则见 [登录与账号隔离](docs/登录与账号隔离.md)。没有默认管理账号或默认密码。

「审计与标准配置」位于 `/admin/governance`，可查看跨账号调用元数据、选择企业岗位、查看质量统计并执行留痕的指定岗位治理操作。投递和消息列表支持分页与全历史搜索；求职者粘贴 JD 的对照支持手工画像兜底。2026-10-14 验收问题的对应修复、测试证据和未验证事项见 [修复记录](docs/验收问题修复记录-2026-10-14.md)。


管理端与用户端现使用独立 Cookie 和标签页通知频道，可在同一浏览器同时登录不同账号。求职者从 `http://127.0.0.1:8501/login?role=candidate` 登录，工作人员从 `http://127.0.0.1:8501/admin/login` 登录；各自退出不会退出另一端。管理账号设置密码使用 `/admin/forgot-password`。首次升级后重新登录管理端即可，普通账号资料保留；同一账号重设密码仍会撤销该账号的全部旧会话。

Word 导入：DOCX 使用受限 ZIP/XML 提取正文和表格；旧 DOC 需要系统安装 `antiword` 并加入 PATH（Linux：`sudo apt-get install antiword`，Docker 镜像已包含）。Word 原件保留供本人下载，页面展示提取文字；加密、损坏、图片正文及超限文件会提示错误。
