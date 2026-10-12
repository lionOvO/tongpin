# 同频 · 人才发掘 Agent 系统

基于文件夹中的 SRS 与 UI 文档实现的双边偏好匹配原型。前端使用 Streamlit，后端使用 FastAPI，业务数据持久化到 SQLite 的十五张表。

## 本地启动（Windows）

双击项目根目录的 **`一键启动.bat`**。脚本优先使用项目虚拟环境；缺少环境或必要依赖时自动创建并安装，前后端就绪后自动打开浏览器。首次安装需要联网；没有 Python 时需先安装 Python 3.13。

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
.\.venv\Scripts\python.exe -m streamlit run web/Home.py --server.address=127.0.0.1 --server.port=8501
```

## 已提供的流程

- 企业偏好与求职者偏好、双方原文对照、无法判断态、历史快照与过期标记。
- 岗位创建、结构化画像编辑与版本确认、需求澄清与三类 JD 诊断。
- PDF/JSON/TXT 批量导入、解析失败隔离、初筛标记、逐维能力报告与技能行为证据。
- 人工确认、关系修正、打回、三次连续打回暂停、校准记忆确认与删除。
- 仅确认报告参与候选人比较、并列排序、默认无联系方式的 CSV 导出。
- 求职者本人岗位对照、粘贴 JD、自选岗位集合排序、量规差距说明。
- 聚合岗位基准及样本不足拦截、审计、成本估算、隔离检查、锚定样本漂移检查。
- 版本化配置、标准包导入导出、清理合成数据、数据库备份与引用检查。

首次启动装载三位虚构求职者与三个合成岗位。能力报告处于待确认状态，须在前端人工确认后才会出现在比较页。所有示例均明确标记为合成。

## AI 与演示模式

默认 `LLM_MODE=demo`，使用可复现的本地文本规则，无需密钥。界面明确显示「本地演示规则」。这是联调与演示模式，不宣称模型准确率。

真实模型调用在 `.env` 配置：

```dotenv
LLM_MODE=deepseek
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

重启后，JD 与能力证据整理会调用模型；偏好匹配、成绩换算、技能汇总与排序仍由确定性代码执行。每次模型调用记录输入哈希、prompt 版本、时长、token 和估算费用。结构化输出失败重试一次，失败不保存半成品报告。费用单价在 `.env` 配置，示例值不是当前官方报价。

## 本地向量检索（可选）

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-vector.txt
```

预下载 `BAAI/bge-m3` 和 `BAAI/bge-reranker-base`，设置 `VECTOR_ENABLED=true`，重启。使用 SentenceTransformer 做向量编码，CrossEncoder 做重排；索引 metadata 隔离 owner、env 和来源。大模型权重需额外磁盘与内存。默认主流程无需这些依赖。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=./artifacts/pytest-local
.\.venv\Scripts\python.exe scripts/browser_check.py
```

浏览器脚本使用本机 Edge 的无头模式，检查企业与求职者页面、响应式、控制台异常和关键交互，截图保存在 artifacts。Linux 可设 `PLAYWRIGHT_BROWSER` 指定浏览器可执行文件。

独立人工标注集可用 `scripts/evaluate.py` 计算一致率、证据覆盖、重复一致性和 baseline 差值；格式和实测限制见 [评测说明](docs/evaluation.md)。运行验收记录见 [验证记录](docs/verification.md)。

## Docker / 腾讯云

```bash
cp .env.example .env
chmod 600 .env
docker compose up --build -d --wait
```

默认只映射回环地址，腾讯云演示可用 `ssh -L 8501:127.0.0.1:8501 用户@服务器` 后访问本机 8501。`deploy.sh` 在升级前暂停写入并备份数据卷。业务与可编辑配置均在持久化卷。可选向量版使用 `WITH_VECTORS=true` 构建并预下载模型。

本版本没有正式登录或用户认证，`X-Demo-Actor` 只用于演示隔离。APP_ENV=prod 禁止写入。接真实生产简历前，需要补齐认证、授权、告知同意、留存与删除权流程。当前本地可以导入个人材料供自测，不应公网部署处理他人真实简历。

## 项目结构

```text
app/            API、服务、Agent、确定性规则与 SQLite
web/            Streamlit 页面、视觉样式与组件
config/         默认版本化判据、偏好维度与措辞
tests/          规则与 API 业务验收
scripts/        浏览器验证与辅助工具
docs/           实现口径和验收记录
docker/         两个服务的 Dockerfile
data/           运行数据、原文、配置修订和备份（不入库）
```

文档中尚未提供的完整 PRD 与上游量规已在 `docs/implementation-decisions.md` 标明。当前量规明确为待校准草案；真实模型效果和完整基准指标需要提供人工标注集后实测，不以自动化测试冒充模型评测。
