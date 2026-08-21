# 部署到云服务流程文档

本文档描述如何把「AI 辅助测试用例生成平台」部署到云服务。项目是 FastAPI + 纯静态前端的 Python 应用，已配套 `Dockerfile` / `docker-compose.yml` / `.dockerignore`，推荐用容器方式部署。

---

## 0. 部署前必读:这个应用有什么特点

在选方案前，先明确它的几个关键约束，直接决定了你要怎么部署:

| 特点 | 影响 |
| --- | --- |
| 依赖外部 LLM API(openai/anthropic/deepseek) | 服务器必须能访问对应 API；需要配置 API Key，注意网络与费用 |
| 默认用 SQLite 本地文件(`data/app.db`) | 数据落在磁盘上，容器/机器重建会丢；生产建议切 PostgreSQL |
| 会把上传的配图落盘到 `data/uploads/` | 需要持久化磁盘(volume)，否则重启丢图 |
| 需求理解/用例生成是**同步阻塞**调用(单条 30~60 秒) | 单请求耗时长，需要放宽反向代理/网关的超时时间 |
| **未内置鉴权** | 不能直接裸奔在公网，必须加访问控制(见第 6 节) |

---

## 1. 方案选择

按由简到繁排列，按团队情况选一个即可:

- **方案 A(推荐入门):单台云服务器 + Docker Compose** —— 最简单，一台 2C4G 的云主机就能跑，数据放本机磁盘。适合内部工具、小团队。
- **方案 B:云服务器 + Docker + 托管 PostgreSQL** —— 在 A 的基础上把数据库换成云厂商的 RDS/托管 PG，数据更安全，可扩容。
- **方案 C:容器托管平台(阿里云 ACK / 腾讯云 TKE / K8s / Cloud Run 等)** —— 需要弹性伸缩、多实例时用。

下面详述 A / B，并给出 C 的要点。

---

## 2. 准备工作(所有方案通用)

### 2.1 一台可访问外网的云服务器
- 配置建议:最低 2 核 4G，磁盘 ≥ 20G(装了 numpy/scikit-learn 依赖后镜像约 500MB~1G)。
- 系统:Ubuntu 22.04 / Debian 12 等主流 Linux。
- 安全组/防火墙:放行 SSH(22) 和你计划对外的端口(如 80/443)。**不要直接把 8000 裸露公网**。

### 2.2 安装 Docker 与 Docker Compose
```bash
# Ubuntu/Debian 一键安装官方 Docker
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker
docker version && docker compose version
```

### 2.3 拿到应用代码
```bash
git clone <你的仓库地址> ai-testcase
cd ai-testcase
```

### 2.4 准备 LLM API Key
根据 `LLM_PROVIDER` 选择，准备好对应的 Key(openai / anthropic / deepseek 三选一)。
> 如果只是想先跑通链路、不接真实模型，可先用 `LLM_PROVIDER=mock`(返回假数据，零成本)。

---

## 3. 方案 A:单机 Docker Compose 部署(推荐入门)

### 3.1 写好环境变量文件 `.env`
```bash
cp .env.example .env
vi .env
```
按需填写(生产建议最少配置如下):
```ini
# 数据库:留空即用 SQLite(数据在 ./data 里,已通过 volume 持久化)
DATABASE_URL=

# 只允许你的前端域名跨域访问;若前后端同域可保持简单,生产不建议用 *
CORS_ORIGINS=https://testcase.yourcompany.com

# LLM 供应商与 Key
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-xxxx
LLM_MODEL=

# RAG 检索:默认本地 tfidf 零成本;要更好效果可设 openai(需 OPENAI_API_KEY)
RAG_EMBEDDING_PROVIDER=tfidf

# 可选:飞书文档导入(不填则该功能不可用,不影响手动录入)
FEISHU_APP_ID=
FEISHU_APP_SECRET=
```

### 3.2 构建并启动
```bash
docker compose up -d --build
```
- 首次构建会编译/下载依赖，约几分钟。
- 启动后数据会持久化到宿主机的 `./data` 目录。

### 3.3 验证
```bash
# 健康检查
curl http://127.0.0.1:8000/health      # 期望 {"status":"ok"}
# 查看日志
docker compose logs -f app
# 查看容器状态(含 healthcheck)
docker compose ps
```

此时应用已在服务器 `8000` 端口运行，但还只监听在本机/容器网络，**下一步用 Nginx 对外并加 HTTPS**(见第 5、6 节)。

### 3.4 日常运维命令
```bash
docker compose restart app        # 重启
docker compose down               # 停止并移除容器(数据仍在 ./data)
git pull && docker compose up -d --build   # 更新代码后重新部署
docker compose logs -f app        # 实时日志
```

---

## 4. 方案 B:切换到托管 PostgreSQL(生产推荐)

SQLite 适合演示，但生产环境(数据安全、备份、多实例)建议用 PostgreSQL。

### 4.1 增加数据库驱动
在 `requirements.txt` 末尾加一行后重新 build:
```
psycopg2-binary>=2.9.0
```

### 4.2 准备 PostgreSQL
二选一:
- **云厂商托管 RDS**(推荐):在阿里云/腾讯云/AWS 创建一个 PostgreSQL 实例，拿到连接信息。
- **自建**:解开 `docker-compose.yml` 里注释掉的 `db` 服务和 `volumes`。

### 4.3 配置连接串
在 `.env` 里设置(格式:`postgresql+psycopg2://用户:密码@主机:5432/库名`):
```ini
DATABASE_URL=postgresql+psycopg2://app:yourpassword@db:5432/aitestcase
```
> 应用启动时会自动建表(`init_db()`)，无需手动执行建表 SQL。

### 4.4 重新部署
```bash
docker compose up -d --build
```

> 注意:切到 PostgreSQL 后可以安全地用多 worker 提升并发。把 `Dockerfile` 的 `CMD` 改为:
> `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4`
> (SQLite 下**不要**开多 worker，会锁库。)
> 另外:上传的配图仍落在 `data/uploads/`，多实例时需换成对象存储(见第 8 节)。

---

## 5. 反向代理与超时设置(必做)

用 Nginx 把公网流量转发到应用，并**放宽超时**(因为生成用例是长请求，默认 60s 超时会中断)。

`/etc/nginx/conf.d/aitestcase.conf`:
```nginx
server {
    listen 80;
    server_name testcase.yourcompany.com;

    client_max_body_size 20m;   # 允许上传配图

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 关键:用例生成单请求可能 30~60 秒,放宽超时避免 504
        proxy_read_timeout 180s;
        proxy_send_timeout 180s;
    }
}
```
```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 6. 加访问控制与 HTTPS(必做,应用本身没有鉴权)

应用**未内置任何鉴权**，绝不能直接暴露在公网。至少做到以下之一:

- **内网/VPN 限制**:安全组只放行公司内网/VPN 网段。
- **Nginx Basic Auth**:简单粗暴加一层账号密码。
  ```bash
  sudo apt install apache2-utils -y
  sudo htpasswd -c /etc/nginx/.htpasswd yourname
  # 在上面的 location / 里加:
  #   auth_basic "Restricted"; auth_basic_user_file /etc/nginx/.htpasswd;
  ```
- **HTTPS**:用 Let's Encrypt 免费证书。
  ```bash
  sudo apt install certbot python3-certbot-nginx -y
  sudo certbot --nginx -d testcase.yourcompany.com
  ```

---

## 7. 方案 C:容器托管平台(K8s / Cloud Run 等)要点

如果要弹性伸缩、多实例，用容器编排平台。核心改造点:

1. **无状态化**:多副本时 SQLite 与本地 `data/uploads` 都不能用。
   - 数据库 → 托管 PostgreSQL(见方案 B)。
   - 上传文件 → 对象存储(见第 8 节)。
2. **镜像推送**:把 `Dockerfile` build 出的镜像推到镜像仓库(ACR/TCR/Harbor 等)。
   ```bash
   docker build -t <registry>/ai-testcase:v1 .
   docker push <registry>/ai-testcase:v1
   ```
3. **配置注入**:API Key、DATABASE_URL 用平台的 Secret/环境变量注入，不要打进镜像。
4. **健康检查**:就绪/存活探针都指向 `GET /health`。
5. **超时**:网关(Ingress/LB)的超时同样要放宽到 ≥180s。
6. **资源**:单实例建议 request 0.5C/512Mi，limit 1C/1Gi 起步(numpy/sklearn 占内存)。

---

## 8. 生产加固清单(建议逐项确认)

- [ ] 数据库已切 PostgreSQL 并配置**自动备份**。
- [ ] `data/`(SQLite/上传图)已挂载持久化 volume 或已迁移对象存储。
- [ ] 已加访问控制(VPN / Basic Auth / 鉴权网关)。
- [ ] 已启用 HTTPS。
- [ ] `CORS_ORIGINS` 收窄为具体域名，不用 `*`。
- [ ] 反向代理与网关超时 ≥ 180s。
- [ ] API Key 通过环境变量/Secret 注入，未提交进 git(`.env` 已在 `.gitignore`)。
- [ ] 已配置日志收集与容器自动重启(`restart: unless-stopped`)。
- [ ] (可选)高并发场景把同步生成改造成异步任务队列(Celery/RQ)—— 见 README「已知限制」。

### 关于文件上传迁移对象存储
目前配图落在 `data/uploads/{requirement_id}/`(见 `app/config.py` 的 `UPLOAD_DIR`)。单机部署无需改动;上多实例时需要把 `app/services/image_service.py` 的读写改为对象存储(OSS/COS/S3)。这是方案 C 的前置改造项。

---

## 9. 最小上线路径(TL;DR)

想最快上线一个可用的内部工具:

```bash
# 1. 云服务器装 Docker
curl -fsSL https://get.docker.com | sh

# 2. 拉代码、配 .env(填 LLM_PROVIDER + API Key)
git clone <repo> ai-testcase && cd ai-testcase
cp .env.example .env && vi .env

# 3. 起服务
docker compose up -d --build

# 4. 配 Nginx 反代 + HTTPS + Basic Auth(第 5、6 节)
# 5. 访问 https://你的域名/ 开始使用
```
数据默认存本机 `./data`，记得定期备份该目录(或按方案 B 切 PostgreSQL)。
```
tar czf backup-$(date +%F).tgz data/   # 简易备份
```
