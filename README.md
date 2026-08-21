# AI 辅助生成测试用例平台

需求录入 → AI 需求理解 → AI 分类型用例生成 → 人工审核 → 导出。详细架构设计见 [docs/DESIGN.md](docs/DESIGN.md)。

## 目录结构

```
app/                    FastAPI 服务
  main.py                应用入口(同时挂载 web/ 静态文件)
  config.py               环境变量配置
  database.py              SQLAlchemy 引擎/会话(默认 SQLite,可切换 PostgreSQL)
  models.py                ORM 模型:requirement / requirement_analysis / test_case / generation_batch
  api_schemas.py            API 请求/响应 Pydantic 模型
  llm/                      LLM 调用客户端 + prompt 加载 + LLM 输出结构校验(服务和评测脚本共用)+ retrieval(RAG 检索)
  services/                 业务逻辑:pipeline_service(需求理解+用例生成,已接入 RAG)、export_service(导出)、knowledge_service(知识库入库/检索)
  routers/                   API 路由:requirements、cases、knowledge

web/                     前端页面(纯 HTML/CSS/JS,无需构建工具)
  index.html               页面结构
  styles.css                样式
  app.js                    调用后端 API 的交互逻辑

prompts/                 Prompt 模板(jinja2)
eval/                    Prompt 效果验证环境,见 eval/README.md
docs/DESIGN.md           技术方案设计文档
```

## 快速开始

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env,填入 LLM_PROVIDER(openai/anthropic/deepseek/mock)对应的 API Key

uvicorn app.main:app --reload --port 8000
```

启动后:
- 打开 `http://127.0.0.1:8000/` 使用前端页面(需求录入 → AI 理解 → AI 生成用例 → 审核编辑 → 导出)
- 打开 `http://127.0.0.1:8000/docs` 查看自动生成的接口文档

数据库默认是本地 SQLite 文件(`data/app.db`),无需额外安装数据库即可跑起来。

## 核心接口速览

```
POST   /api/requirements                创建需求
POST   /api/requirements/fetch-link     抓取飞书文档链接的标题+正文(不落库,供前端填充预览)
POST   /api/requirements/{id}/images    上传需求配图(界面原型/流程图/截图,multipart)
GET    /api/requirements/{id}/images    该需求的配图列表
GET    /api/requirements/images/{id}/raw 读取图片原图
DELETE /api/requirements/images/{id}    删除某张配图
GET    /api/requirements                需求列表
GET    /api/requirements/{id}           需求详情(含理解结果)
POST   /api/requirements/{id}/analyze   触发 AI 需求理解
POST   /api/requirements/{id}/generate  触发 AI 用例生成(body: {"case_types": ["functional","boundary","exception"]})
GET    /api/requirements/{id}/cases     该需求下的用例列表(支持按类型/审核状态筛选)
POST   /api/requirements/{id}/cases     人工手动补充用例(AI 没覆盖到的场景,来源标记为 manual)
GET    /api/requirements/{id}/stats     用例统计:来源分布(召回率)+ 审核分布(采纳率)

GET    /api/cases/{id}                  用例详情
PATCH  /api/cases/{id}                  编辑用例内容 / 更新审核状态
DELETE /api/cases/{id}                  删除用例
POST   /api/cases/export                导出用例为 xlsx/csv

POST   /api/knowledge/documents               手动录入知识库文档(测试规范/术语表等)
GET    /api/knowledge/documents?query=xxx     检索/浏览知识库
DELETE /api/knowledge/documents/{id}          删除知识库文档
POST   /api/knowledge/import-accepted-cases   把已审核通过(accepted)的用例批量导入知识库
```

## 典型使用流程

```bash
# 1. 创建需求
curl -X POST localhost:8000/api/requirements -H "Content-Type: application/json" \
  -d '{"title": "标题", "content": "需求描述..."}'

# 2. 触发需求理解(id 为上一步返回的需求 id)
curl -X POST localhost:8000/api/requirements/1/analyze

# 3. 触发用例生成
curl -X POST localhost:8000/api/requirements/1/generate -H "Content-Type: application/json" -d '{}'

# 4. 查看生成的用例
curl localhost:8000/api/requirements/1/cases

# 5. 人工审核/编辑某条用例
curl -X PATCH localhost:8000/api/cases/1 -H "Content-Type: application/json" \
  -d '{"review_status": "accepted"}'

# 6. 导出
curl -X POST localhost:8000/api/cases/export -H "Content-Type: application/json" \
  -d '{"requirement_id": 1, "format": "xlsx"}' -o cases.xlsx

# 7. 把这批已采纳的用例导入知识库,供后续其他需求生成时参考(前端也有"导入知识库"按钮)
curl -X POST localhost:8000/api/knowledge/import-accepted-cases -H "Content-Type: application/json" -d '{}'
```

## RAG 知识库

- 用途:生成用例时,自动检索知识库里相关的历史优质用例,作为额外的 few-shot 示例注入 prompt,让新生成的用例风格更贴近团队习惯
- 数据来源:主要靠"导入已采纳用例"积累,也可以用 `POST /api/knowledge/documents` 手动录入测试规范/术语表
- 检索方式:默认 TF-IDF 本地检索(`RAG_EMBEDDING_PROVIDER=tfidf`,零成本,无需 API key);设置 `RAG_EMBEDDING_PROVIDER=openai` 并配置 `OPENAI_API_KEY` 后切换到语义 embedding 检索,效果更好
- 检索会自动排除"当前需求自己"的样例,避免同需求内自我复读;跨需求场景才是它真正发挥价值的地方
- 详细设计见 [docs/DESIGN.md](docs/DESIGN.md) 第 4.2 节

## 需求配图(多模态需求理解)

在"新建需求"弹窗里可选择上传若干配图(界面原型图、交互流程图、接口/字段截图等),随需求一起保存。

- 触发时机:配图在 **AI 需求理解**(`/analyze`)阶段随需求文本一起交给模型;用例生成阶段复用需求理解产出的结构化结果,因此图片信息会自然传导到用例生成,不必二次上传图片。
- 模型要求:仅 **支持视觉的模型**(`LLM_PROVIDER=openai` / `anthropic`,且用对应视觉模型如 `gpt-4o`、`claude-3-5-sonnet`)会真正"看图"。`deepseek`(官方 API 纯文本)与 `mock` 会自动跳过图片、仅用文本,流程不受影响。
- 存储:图片落盘在 `data/uploads/{requirement_id}/` 下(已被 `.gitignore` 忽略),数据库只记录相对路径与元信息。
- 限制:默认单个需求最多 6 张、单张 ≤ 8MB,支持 png/jpeg/webp/gif,可用环境变量覆盖(见 `.env.example`)。

## 从飞书文档链接导入需求

在"新建需求"弹窗里粘贴飞书文档链接(如 `https://xxx.feishu.cn/docx/xxxxx`)点"抓取",后端会直连飞书开放平台 API 拉取纯文本,自动填入标题和描述,确认后即可创建。

启用前提:在飞书开放平台创建企业自建应用,拿到 `app_id`/`app_secret`,开通云文档读取权限,填入 `.env`:

```
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
```

- 支持新版文档(`/docx/`)和 wiki 节点(`/wiki/`,底层需为 docx);旧版 `/docs/` 暂不支持。
- 未配置凭证时,该功能会返回明确提示,不影响手动粘贴录入。
- 抓取逻辑在 `app/services/doc_fetcher.py`,设计成可扩展结构,后续接入 TAPD、普通网页时新增对应 fetch 函数即可。

## 已知限制 / 后续规划

- 需求理解/用例生成是同步阻塞调用(单条需求走完约 30~60 秒),MVP 阶段够用;并发量上来后需要改成异步任务队列(Celery/RQ)+ 轮询或 WebSocket 推进度。
- RAG 知识库检索目前是 TF-IDF/openai embedding 二选一,量大后(万级以上文档)应迁移到 pgvector/Milvus 专用向量库。
- 已支持从飞书文档链接导入需求;TAPD 需求/缺陷、普通网页的导入待接入(`doc_fetcher` 已预留扩展点)。
- 暂未接入执行平台(如 Lego)回写。
- 未加鉴权,仅适合内部工具场景使用。

对应的 Prompt 效果验证环境见 [eval/README.md](eval/README.md)。
