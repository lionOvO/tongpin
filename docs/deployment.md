# 自行部署同频

本指南面向新的开源部署，不依赖原作者的服务器、账号或域名。项目中其他部署验收记录描述的是特定时间的环境，不应直接照抄 IP、端口或路径。

## 服务组成

| 服务 | 职责 | 默认访问范围 |
| --- | --- | --- |
| `web` | Nginx 托管 Vue，并代理 `/api/` | 宿主机回环 `127.0.0.1:18082` |
| `api` | FastAPI、后台任务、SQLite 与私有材料 | Compose 私有网络，不发布 API 端口 |
| 宿主机反向代理 | 域名与受信任 HTTPS 证书 | 公网 443，由部署者配置 |
| 外部服务 | DeepSeek、阿里云号码认证 PNVS | API 服务出站访问 |

使用 Docker Engine 与 Docker Compose v2。需为构建和运行预留资源；当前默认 API 预算为 1 CPU / 1 GiB，web 为 0.5 CPU / 192 MiB，构建所需空间与内存另计。默认不下载本地向量模型。

## 1. 下载与配置

```bash
git clone https://github.com/lionOvO/tongpin.git
cd tongpin
umask 077
cp .env.server.example .env
chmod 600 .env
```

在服务器编辑 `.env`：填写自己的 DeepSeek key、可用模型名称、短信 access key、secret、签名和模板。参考 [认证配置](登录与账号隔离.md)。不要把密钥写到前端环境变量、命令日志或提交记录中。

`docker-compose.server.yml` 固定生产环境、关闭自动合成数据、使用真实模型模式，并要求 DeepSeek key。保留 `SESSION_COOKIE_SECURE=true`，由受信任的 HTTPS 入口访问。`WEB_PORT` 若冲突，可改为其他空闲回环端口，代理上游同步修改。

## 2. 构建与启动

```bash
docker compose -f docker-compose.server.yml config --quiet
sh deploy-server.sh
export RELEASE_TAG=$(cat .release-tag)
docker compose -f docker-compose.server.yml ps
curl --fail http://127.0.0.1:18082/api/health
```

脚本先构建镜像；升级时暂停本项目写入，备份数据卷，然后等待健康检查。API 固定一个 Uvicorn worker，不能直接增加 worker 数量扩容进程内后台任务。

## 3. 配置 HTTPS 入口

将自己域名的 HTTPS 反向代理指向 `http://127.0.0.1:18082`。示例核心配置如下；证书路径、域名、端口与其他站点应按实际环境调整：

```nginx
server {
    listen 443 ssl;
    server_name tongpin.example.com;
    ssl_certificate     /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    client_max_body_size 12m;
    location / {
        proxy_pass http://127.0.0.1:18082;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

`proxy_buffering off` 让流式回答及时到达浏览器。配置后先执行 `nginx -t`，再 reload。HTTPS 设置完成前，通过回环健康接口验收服务，不将未完成 TLS 的地址当作生产登录入口。若反向代理也运行在容器中，应通过正确的容器网络连接，不能使用该容器自己的回环地址访问宿主机。

## 4. 首次验收与管理员

首页、登录、静态资源、`/api/health` 应正常；未登录读取私有资料应被拒绝。用自己的手机号验证注册，确认求职者与招聘者权限隔离。招聘企业经真实资料审核后才能使用招聘空间。

工作人员先注册，再由维护者授权；没有默认管理员密码：

```bash
docker compose -f docker-compose.server.yml exec api \
  python scripts/manage_accounts.py promote-admin --phone 工作人员手机号
```

管理入口为 `/admin/login`，与普通用户入口分离。不要把测试夹具的合成认证作为真实企业审核结果。

## 5. 更新、备份与回滚

更新代码时保留服务器 `.env`、`.release-tag`、`backups/` 和 `talent_data` 数据卷。先核对当前改动和发布版本，再执行 `sh deploy-server.sh`。部署脚本保存的旧镜像信息与数据备份位于 `backups/`；应将备份复制到独立存储。

如需恢复旧应用镜像，核对备份中的 API/web 标签，选择同一版本，并检查新旧数据库结构兼容后执行：

```bash
RELEASE_TAG=旧版本标签 docker compose -f docker-compose.server.yml up -d --no-build --wait
```

回滚后同步记录 `.release-tag`。数据恢复需先停止写入、备份现状并核对恢复范围，不能直接覆盖正在写入的 SQLite 文件。`docker compose down -v` 会删除数据卷，不能用作正常升级命令。

排查时优先查看本项目日志：

```bash
export RELEASE_TAG=$(cat .release-tag)
docker compose -f docker-compose.server.yml logs --tail=100 api web
```

分享日志前隐藏密钥、账号和简历正文。更详细的维护记录见 [原部署说明](服务器部署.md)，其中的实例地址不属于开源运行所需配置。
