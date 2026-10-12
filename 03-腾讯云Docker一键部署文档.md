# 腾讯云 Linux 服务器 Docker 一键部署操作文档：人才发掘 Agent 系统

> 状态：v1.5｜编制日期：2026-10-08｜v1.5 更新：2026-10-10（**同步 PRD v2.3 产品伦理收口**：部署验证与演示脚本新增**呈现纪律断言**——①**企业端页面不得出现"档位/评级/B1~B5"与阈值语义**；②**企业端与求职者端结果页首屏与页脚须含 AI 偏差提示**；③**演示前须核查 demo 脚本与 README 不含阈值词**。另：措辞映射与偏差提示文案随 `config/presentation` 纳入配置资产挂载卷）｜v1.4 更新：2026-10-10（**同步 PRD v2.2「PM 层为核心功能」**：部署范围随 M1 调整——**M1 现含 PM 层与 RQ-001，故部署验证须覆盖"双边填报 → 匹配 → 档位依据"主链路**；另：**演示前置需执行数据清理（SYS-005），确保对外展示数据带 `data_origin` 标注**）｜v1.3 更新：2026-10-10（**同步 13 号文 v1.2 定位**：§11 数据清理覆盖全 **15 表**，新增 `match_results` 孤儿快照引用校验与 `preference_submissions` 残留检查）｜v1.2 更新：2026-10-09（**同步 PRD v2.0 去评分化**：接口 `/scores*`→`/assessments*`、配置 `weight_templates.json`→`priority_templates.json`、一致性验收改档位一致率、缺陷阈值改档位差）
> 依据：《PRD：人才发掘 Agent 系统 v2.1（结构版本 v2.3.2）》《docs/recruit/01 架构设计与数据库设计 v1.7》《docs/07 M0 产出-定级量规与配置表 v0.9.6》
> 目标：单台腾讯云 CVM 以 docker compose 一键拉起 FastAPI + Streamlit + SQLite + Chroma（卷持久化）
> 标注【待确认】处为需按实际账号/环境填充或评审确认的值

## 目录

- [1. 服务器环境准备](#1-服务器环境准备)
- [2. Docker 与 Docker Compose 安装](#2-docker-与-docker-compose-安装)
- [3. 项目结构与镜像构建](#3-项目结构与镜像构建)
- [4. docker-compose 编排详解](#4-docker-compose-编排详解)
- [5. 环境变量与密钥配置](#5-环境变量与密钥配置)
- [6. 一键部署脚本](#6-一键部署脚本)
- [7. 数据与配置初始化](#7-数据与配置初始化)
- [8. 部署验证](#8-部署验证)
- [9. 常见问题排查](#9-常见问题排查)
- [10. 回滚方案](#10-回滚方案)

---

## 1. 服务器环境准备

### 1.1 规格建议

| 项 | 建议 | 理由 |
|----|------|------|
| 机型 | 腾讯云 CVM 标准型，**4 核 8G 起** | bge-m3 + bge-reranker 本地推理内存占用高，2G 必 OOM |
| 系统盘 | 50G SSD 起 | PyTorch + 模型权重约 2-3G，简历原文与向量库预留 |
| 操作系统 | Ubuntu 22.04 LTS（本档以此为例） | PRD 未锁定 OS |
| 带宽 | ≥5Mbps | Streamlit 页面与 LLM 响应 |

### 1.2 安全组配置

| 方向 | 端口 | 源 | 用途 |
|------|------|----|------|
| 入站 | 22 | 个人办公 IP | SSH |
| 入站 | 8501 | 个人 IP（或 0.0.0.0/0 限演示期） | Streamlit HR 工作台 |
| 入站 | 8000 | 仅本机/容器内网 | FastAPI（不对公网） |

> **合规提醒**：系统处理简历数据（PII 面），即使 demo 使用合成数据，也**不建议长期对公网开放 8501**；对外演示期结束后立即收缩安全组。PRD §10 已声明本期无鉴权。

### 1.3 系统初始化

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git ufw unzip
sudo ufw allow 22/tcp && sudo ufw allow 8501/tcp && sudo ufw --force enable
sudo timedatectl set-timezone Asia/Shanghai
```

## 2. Docker 与 Docker Compose 安装

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
docker version

sudo apt install -y docker-compose-plugin
docker compose version

# 镜像加速（地址按腾讯云控制台"容器镜像服务-镜像加速器"页面替换）【待确认：加速地址】
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": ["https://你的加速地址.mirror.aliyuncs.com"]
}
EOF
sudo systemctl restart docker
```

## 3. 项目结构与镜像构建

### 3.1 仓库结构（对应架构文档 §2）

```
.
├── app/                        # FastAPI 服务层 + Agent 编排层
│   ├── main.py                 # 路由：/jobs /resumes /batches /assessments /reviews
│   │                           #       /candidates /audit /config /health
│   ├── orchestrator.py         # Agent 编排器（任务状态机 + 失败降级 + 熔断）
│   ├── agents/                 # jd_agent / matching_agent / evaluation_agent / audit_agent
│   ├── deterministic/          # 规则引擎 / 成绩标准化落档 / 档位汇总与排序键（禁调 LLM）
│   ├── security/               # 敏感属性剥离、PII 脱敏、审计写入
│   └── models.py               # Pydantic 模型（能力定级报告 schema 等）
├── web/                        # Streamlit HR 工作台（P1~P7 页面）
├── config/                     # 配置资产（版本化 JSON，只读挂载）
│   ├── rubric.v0.9.json        # 量规全文（五档行为锚点，无分数）
│   ├── priority_templates.json # 维度优先级模板（保存时校验：至少 1 个 P0、同维度不重复）
│   └── major_domain_map.json   # 专业-领域映射表
├── pipelines/                  # 合成简历生成、导入、评测脚本
├── eval/                       # 50 对标注集 + 评测脚本（run.py → report.md）
├── data/                       # 运行期数据（compose 卷挂载）
│   ├── init/resumes/           # 初始合成简历
│   └── raw_files/              # 简历原文
├── docker/                     # api.Dockerfile / web.Dockerfile
├── docker-compose.yml
├── deploy.sh
├── requirements-api.txt
└── .env                        # 不入库
```

### 3.2 Dockerfile

`docker/api.Dockerfile`：

```dockerfile
FROM python:3.11-slim

WORKDIR /srv
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

# 预下载本地模型权重（避免运行时外网拉取失败；约 2.3G）
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('BAAI/bge-m3'); \
    SentenceTransformer('BAAI/bge-reranker-base')"

COPY app/ ./app/
COPY pipelines/ ./pipelines/
COPY eval/ ./eval/
COPY config/ ./config/

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`docker/web.Dockerfile`：

```dockerfile
FROM python:3.11-slim
WORKDIR /srv
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt
COPY web/ ./web/
EXPOSE 8501
CMD ["streamlit", "run", "web/Home.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
```

`requirements-api.txt` 关键依赖：`fastapi uvicorn pydantic chromadb sentence-transformers pandas` + CPU 版 torch（`--index-url https://download.pytorch.org/whl/cpu`，体积减半）；`requirements-web.txt`：`streamlit requests pandas`。【待确认】是否引入 LangGraph（架构文档待确认项 1）；若引入须加入依赖并锁定版本。

## 4. docker-compose 编排详解

```yaml
services:
  api:
    build:
      context: .
      dockerfile: docker/api.Dockerfile
    image: talent-agent-api:${TAG:-latest}
    container_name: talent-api
    env_file: .env
    volumes:
      - agent_data:/srv/data            # SQLite + Chroma + raw_files 持久化
      - ./config:/srv/config:ro          # 配置资产只读（量规/优先级配置/映射）
      - ./data/init:/srv/data/init:ro
    ports:
      - "127.0.0.1:8000:8000"            # 仅回环，不对公网
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 120s                 # 首次启动含模型加载
    restart: unless-stopped

  web:
    build:
      context: .
      dockerfile: docker/web.Dockerfile
    image: talent-agent-web:${TAG:-latest}
    container_name: talent-web
    env_file: .env
    environment:
      - API_BASE_URL=http://api:8000
    ports:
      - "8501:8501"
    depends_on:
      api:
        condition: service_healthy
    restart: unless-stopped

volumes:
  agent_data:
```

要点：

- **单一数据卷 `agent_data`**：SQLite、Chroma、简历原文全部在内，容器重建不丢数据；deploy.sh 在部署前自动备份该卷。
- **配置资产只读挂载**：量规/维度优先级配置/映射表**不经容器内修改**，变更走仓库提交 + 重新部署——保证配置变更可回溯（EV-007 冻结纪律）。
- **API 仅绑回环**：前端经容器内网 `api:8000` 调用；HR 工作台是唯一对外入口。

## 5. 环境变量与密钥配置

`.env`（`chmod 600 .env`，禁止入库）：

```bash
# LLM（唯一外部依赖，可整体替换）
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# 定级与批次控制
ASSESS_RETRY_TIMES=1         # Agent 输出 schema 校验失败重试次数（PRD §11）
BATCH_CONCURRENCY=3          # 定级队列并发；越高成本越快但风险越大
BIAS_ALERT_TIER_GAP=1        # 对照简历对告警阈值：任一维度档位差 ≥N 档（AU-002）
COST_BUDGET_CNY=50           # 单批 token 成本预算上限，超出批次暂停【待确认：预算值】

# 配置资产版本（写入 ability_reports 元信息，可复现性要求）
RUBRIC_VERSION=v0.9
PRIORITY_VERSION=v1
TAG=latest
```

## 6. 一键部署脚本

`deploy.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail

TAG="${TAG:-latest}"
BACKUP_DIR="./backups/$(date +%Y%m%d_%H%M%S)"

echo "[1/6] 前置检查"
command -v docker >/dev/null || { echo "缺少 docker"; exit 1; }
[ -f .env ] || { echo "缺少 .env（见文档第 5 章）"; exit 1; }
grep -q "DEEPSEEK_API_KEY=sk-" .env || { echo ".env 未配置 DEEPSEEK_API_KEY"; exit 1; }
python3 -c "import json,sys; t=json.load(open('config/priority_templates.json')); \
  [sys.exit(f'优先级模板 {k} 缺少 P0 维度') for k,v in t.items() if 'P0' not in v.values()]" \
  || { echo "优先级模板校验失败（至少需 1 个 P0 维度）"; exit 1; }

echo "[2/6] 备份现有数据卷"
if docker volume inspect talent-agent_agent_data >/dev/null 2>&1; then
  mkdir -p "$BACKUP_DIR"
  docker run --rm -v talent-agent_agent_data:/data -v "$PWD/$BACKUP_DIR":/backup \
    alpine tar czf /backup/agent_data.tar.gz -C /data .
  echo "  已备份至 $BACKUP_DIR/agent_data.tar.gz"
fi

echo "[3/6] 构建镜像"
docker compose build

echo "[4/6] 启动服务"
docker compose up -d

echo "[5/6] 健康检查（最长 180s，含模型加载）"
for i in $(seq 1 36); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "  API healthy"; break
  fi
  [ "$i" -eq 36 ] && { echo "健康检查超时，查看日志：docker logs talent-api"; exit 1; }
  sleep 5
done

echo "[6/6] 验证入口"
curl -s http://127.0.0.1:8501 >/dev/null && echo "HR 工作台：http://<服务器IP>:8501"
docker compose ps
echo "部署完成。"
```

使用：`git pull && chmod +x deploy.sh && ./deploy.sh`。幂等：重复执行 = 重建 + 滚动重启 + 先备份。

## 7. 数据与配置初始化

首次启动后执行（容器内）：

```bash
# 1) 校验并装载配置资产（量规版本/维度优先级配置/专业映射表）
docker exec talent-api python -m pipelines.load_config --check

# 2) 导入初始合成简历（含刻意构造的对照样本：强相关/弱相关/缺 GPA/无实习/信息不完整）
docker exec talent-api python -m pipelines.import_resumes --dir /srv/data/init/resumes

# 3) （可选）跑评测基线（50 对标注集），输出 eval/report.md
docker exec talent-api python -m eval.run --out /srv/data/eval_report.md
```

> 配置资产（`config/*.json`）为**仓库文件**，变更须提交 + 重新部署；`load_config --check` 失败即拒绝启动，防止非法优先级配置流入定级。

## 8. 部署验证

| 步骤 | 命令/操作 | 预期 |
|------|-----------|------|
| 容器状态 | `docker compose ps` | api、web 均 Up，api healthy |
| 健康检查 | `curl -s http://127.0.0.1:8000/health` | `{"status":"ok"}` |
| 配置装载 | `docker exec talent-api python -m pipelines.load_config --check` | 三份配置资产版本与校验结果输出，无报错 |
| **黄金流** | 浏览器 8501：粘贴 JD → 确认画像 → 导入 10 份合成简历 → 查看三档分批 → 对 top 批发起定级 → 审阅能力定级报告 → 改档 1 次并填理由 → 确认 → 在 P5 排序页看到该候选人 | 全链路走通，无跳转中断 |
| **定级一致性** | 对同一份简历连续定级 3 次 | 各维**档位一致率 ≥90%** 且不跨越 B3/B4 边界（PRD §1.3；可用脚本 `eval.consistency --resume-id`） |
| **证据覆盖率** | 检查任一份报告 | 每个有档位维度均含 ≥1 条简历原文证据（100%） |
| **闸门生效** | 未确认的报告 | 不出现在 P5 排序视图；直接请求 `/candidates/ranking?confirmed_only=false` 需带参数才可见 |
| **敏感属性隔离** | `docker exec talent-api python -m pipelines.audit_prompt --dump-last` | dump 的 Agent 输入中不含性别/年龄/院校等字段（AU-001） |
| 持久化 | `docker compose down && up -d` 后重查报告 | 报告与证据完整（卷未丢） |

## 9. 常见问题排查

| 现象 | 排查 | 处理 |
|------|------|------|
| 构建慢/超时 | 未配镜像加速（第 2 章） | 配加速后重试；模型层可单独缓存 |
| 健康检查超时 | `docker logs talent-api` | 多为模型加载慢；检查内存（`dmesg \| grep -i oom`），4G 内存需升配 |
| 定级大面积失败 | `docker logs talent-api` 查 Agent 调用 | API key/额度问题；schema 校验失败会重试 1 次后入人工队列，**不会产生半成品档位** |
| 成本超预算 | P6 审计中心成本明细 / `COST_BUDGET_CNY` | 批次暂停；降低 `BATCH_CONCURRENCY`、只跑 top 批（漏斗原则） |
| 偏见检测告警频发 | P6 偏见检测表 | 检查量规是否含院校/年龄隐性判据；必要时回退量规版本重校准（EV-007） |
| 报告无证据 | 检查 Evidence 字段 | 多为简历信息不完整导致的证据不足（应显示"证据不足"且**不入档**，而非低档位）；确认缺证据处理配置（EV-004） |
| Chroma 异常/膨胀 | `docker exec talent-api python -m pipelines.rebuild_index` | 从 SQLite + raw_files 重建向量（Chroma 可重建，raw_files 为准） |
| 前端白屏 | `docker logs talent-web`；`curl http://127.0.0.1:8501` | api 未 healthy 导致初始化失败；等 api 就绪后重启 web |
| 端口占用 | `sudo ss -lntp \| grep -E '8501\|8000'` | 释放端口或改映射 |

### 9.5 公网暴露与简历数据

PRD §10 声明本期无鉴权。**简历数据即使为合成，界面与导出也不应长期对公网开放**：演示期开放后立即关闭，或前置 Nginx Basic Auth；`GET /candidates/export` 默认不含联系方式字段（UI 文档待确认项 3）。

## 10. 回滚方案
**应用层回滚**（代码/配置问题）：`TAG=v1.0.0 ./deploy.sh`（镜像 tag 与 git tag 保持一致，发版时 `docker build -t talent-agent-api:vX.Y.Z` 保留历史镜像）。

**配置层回滚**（量规/维度优先级/映射错误）：

```bash
git checkout <上一版本> -- config/
docker compose up -d api      # 配置只读挂载，重启即生效
```

> 配置回滚后**存量报告不回溯重算**（PRD EV-007：新配置对下一批生效）；如需重评须人工对指定报告触发 `POST /assessments/{id}/rerun`。

**数据层回滚**（误操作/脏数据）：

```bash
docker compose stop api web
BACKUP=./backups/<时间戳>/agent_data.tar.gz
docker run --rm -v talent-agent_agent_data:/data -v "$PWD/backups":/backup \
  alpine sh -c "rm -rf /data/* && tar xzf /backup/$(basename $BACKUP) -C /data"
docker compose start api web
```

**LLM 供应商替换**：改 `.env` 的 `DEEPSEEK_BASE_URL`/`DEEPSEEK_MODEL` 并重建 api 容器，其余组件无感（架构文档 §2.2）。

## 11. 数据清理（交付/演示前，SYS-005，v1.1 新增；v1.3 扩充至 15 表）

**适用场景**：测试期用合成数据完整跑通（当作真实数据使用），在**交付演示或开源前**清空合成数据。

**前置**：所有业务表已携带 `data_origin`（synthetic/real）与 `env`（dev/demo/prod）标记（由写入管道统一写入，禁止人工维护）。

**⚠️ v1.3 变更重点**：新增的 **`match_results`、`preference_submissions`、`job_comparison_runs`、`hiring_briefs`、`jd_diagnoses`** 五表**全部是 synthetic 可清理对象**，且 **`match_results` 含双方填报快照哈希**——若只清明细不清快照引用，会留下"指向已删除填报的孤儿匹配结果"，健康检查必须覆盖。

**清理五步**（脚本 `pipelines/purge_synthetic.py`）：

```bash
# 1) 进入维护模式（禁止写入）
docker exec talent-api python -m pipelines.maintenance --on

# 2) 全量备份（复用第 10 章备份机制）
mkdir -p ./backups/purge_$(date +%Y%m%d_%H%M%S)
docker run --rm -v talent-agent_agent_data:/data -v "$PWD/backups":/backup \
  alpine tar czf /backup/purge.tar.gz -C /data .

# 3) 按标记清除：默认仅删 synthetic；必须显式指定非生产 env，否则拒绝执行
docker exec talent-api python -m pipelines.purge_synthetic --env demo --origin synthetic --confirm

# 4) 重算聚合视图（关键：role_benchmarks / 看板）
docker exec talent-api python -m pipelines.recompute_aggregates
docker exec talent-api python -m pipelines.rebuild_index     # 向量库同步重建

# 5) 留痕与验证
docker exec talent-api python -m pipelines.audit --event 数据清理
docker exec talent-api python -m pipelines.health_check --no-orphans
docker exec talent-api python -m pipelines.maintenance --off
```

**清理覆盖范围（15 表，v1.3 更新）**：

| 类别 | 表 | 清理动作 |
|------|---|---------|
| 岗位与画像 | job_profiles、hiring_briefs、jd_diagnoses | 按 `data_origin=synthetic` 删 |
| 简历与批次 | candidates、resumes、batches、ability_reports、review_events、calibration_memory | 同上 |
| **双边填报与匹配（v1.3 新增）** | **preference_submissions、match_results** | **同上；须同时校验 match_results 无孤儿快照引用** |
| **求职者端（v1.3 新增）** | **fit_reports、job_comparison_runs** | 同上 |
| 聚合与审计 | role_benchmarks、audit_logs | **聚合表须重算而非仅删**；audit_logs 保留清理留痕 |
| 向量库 | Chroma `resume_chunks` | 随简历删除同步重建 |

**三条硬约束**：

1. **未指定 env 或指定 `env=prod` → 拒绝执行**（脚本级拦截，不靠人记）；
2. **清除第 4 步不可省**——用合成数据算出的 `role_benchmarks` 若不清算，会以"真实基准"的样子留在界面上（**聚合残留比明细残留更危险**）；**v1.3 补充**：`match_results` 的残留同样危险——它会让人以为"系统真的匹配过"；
3. **清理 ≠ 可以接真实数据**：真实简历需另行补齐告知-同意、留存与删除权、权限体系（PRD §6.3/§10 本期未实现）——故本流程定位为**演示/作品交付前动作**。

**清理后检查项**：看板聚合数为 0 或仅含 real 数据；`role_benchmarks` 无 synthetic 统计；**`match_results` 无孤儿快照引用、`preference_submissions` 无残留**；audit_logs 存在"数据清理"记录；`/health` 正常。

---

## 附：待确认清单

| # | 事项 | 理由 |
|---|------|------|
| 1 | 镜像加速地址 | 按账号控制台获取 |
| 2 | 单批 token 成本预算值（`COST_BUDGET_CNY`） | 需先跑 10 份简历实测单份成本后定 |
| 3 | 是否引入 LangGraph 等编排框架 | 架构文档待确认项 1；影响依赖与镜像体积 |
| 4 | 域名/HTTPS 是否需要 | PRD 未涉及；演示可直接 IP:8501 |
| 5 | 简历原文是否必须留存 PDF | 影响存储与 PII 面（架构文档待确认项 2） |
| 6 | 定时备份策略（cron + COS） | deploy.sh 仅部署时备份；生产化再补 |

> 合规输出声明：本方案为产品设计参考，具体实施请结合公司合规与法务要求确认。
