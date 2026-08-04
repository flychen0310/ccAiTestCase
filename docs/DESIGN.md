# AI 辅助生成测试用例平台 —— 技术方案设计

版本:v0.1  定位:独立平台  AI 能力:商用 LLM API(GPT / Claude 系列)

## 1. 目标与范围

**目标**:输入一条需求(文本/文档/需求单),平台自动理解需求并生成结构化、可执行的测试用例,经人工确认后落库,支撑后续测试执行与追溯。

**MVP 范围**:
- 支持手动粘贴需求文本 / 上传需求文档生成用例
- 生成结构化用例(标题、前置条件、步骤、预期结果、优先级、用例类型)
- 提供人工编辑、审核、批量导出能力
- 记录需求与用例的映射关系,支持后续追溯

**暂不纳入 MVP**(后续迭代):自动拉取 TAPD 需求、自动同步到外部执行平台、执行结果反馈闭环、用例质量自动评分。

## 2. 整体架构

```
┌────────────┐   ┌────────────────┐   ┌────────────────┐   ┌────────────┐   ┌────────────┐
│ 需求接入层  │→ │ 需求理解层(AI) │→ │ 用例生成引擎(AI)│→ │ 质检/评审层 │→ │ 用例管理层  │
│ 文本/文档   │   │ 抽取功能点/    │   │ RAG+Prompt      │   │ 覆盖率校验/  │   │ CRUD/导出/  │
│ 上传/粘贴   │   │ 边界/异常场景  │   │ 分类生成用例    │   │ 人工审核     │   │ 追溯需求   │
└────────────┘   └────────────────┘   └────────────────┘   └────────────┘   └────────────┘
                                              ↑
                                    ┌──────────────────┐
                                    │ 知识库(向量库)     │
                                    │ 历史优质用例/规范  │
                                    └──────────────────┘
```

**技术栈**:
- 前端:React + TypeScript(需求输入、用例预览编辑、审核工作台)
- 后端:Python(FastAPI)—— 负责需求解析编排、LLM 调用、RAG 检索、业务 API
- 数据库:PostgreSQL(业务数据) + pgvector 或 Milvus(向量检索,一期可先用 pgvector 降低运维成本)
- LLM:GPT-4.x / Claude 系列,通过官方 API 调用,统一封装成 `LLMClient` 便于切换供应商
- 部署:Docker Compose(一期),后续可迁移 K8s

## 3. 数据模型

### 3.1 核心表结构

```sql
-- 需求表
CREATE TABLE requirement (
  id            BIGSERIAL PRIMARY KEY,
  title         VARCHAR(255) NOT NULL,
  content       TEXT NOT NULL,           -- 原始需求文本
  source        VARCHAR(32),             -- manual / tapd / upload
  source_ref_id VARCHAR(64),             -- 外部系统需求ID(预留)
  status        VARCHAR(32) DEFAULT 'draft', -- draft/parsing/parsed/failed
  created_by    VARCHAR(64),
  created_at    TIMESTAMP DEFAULT now(),
  updated_at    TIMESTAMP DEFAULT now()
);

-- 需求理解结果(AI拆解出的功能点/规则/场景)
CREATE TABLE requirement_analysis (
  id              BIGSERIAL PRIMARY KEY,
  requirement_id  BIGINT REFERENCES requirement(id),
  feature_points  JSONB,   -- 功能点列表
  business_rules  JSONB,   -- 业务规则
  edge_cases      JSONB,   -- 边界/异常场景
  open_questions  JSONB,   -- 待澄清问题
  raw_llm_output  TEXT,
  created_at      TIMESTAMP DEFAULT now()
);

-- 测试用例表
CREATE TABLE test_case (
  id              BIGSERIAL PRIMARY KEY,
  requirement_id  BIGINT REFERENCES requirement(id),
  title           VARCHAR(255) NOT NULL,
  precondition    TEXT,
  steps           JSONB,          -- [{step, expected}, ...]
  case_type       VARCHAR(32),    -- functional/boundary/exception/compat/perf/security
  priority        VARCHAR(16),    -- P0/P1/P2
  review_status   VARCHAR(32) DEFAULT 'pending', -- pending/accepted/rejected/edited
  review_comment  TEXT,
  gen_batch_id    BIGINT,         -- 关联生成批次,便于追溯 prompt/model 版本
  created_at      TIMESTAMP DEFAULT now(),
  updated_at      TIMESTAMP DEFAULT now()
);

-- 生成批次(记录每次调用LLM的元信息,便于问题追溯和效果评估)
CREATE TABLE generation_batch (
  id              BIGSERIAL PRIMARY KEY,
  requirement_id  BIGINT REFERENCES requirement(id),
  model_name      VARCHAR(64),
  prompt_version  VARCHAR(32),
  token_usage     INT,
  cost_estimate   NUMERIC(10,4),
  status          VARCHAR(32),
  created_at      TIMESTAMP DEFAULT now()
);

-- 知识库文档(用于RAG检索的历史用例/规范)
CREATE TABLE knowledge_doc (
  id          BIGSERIAL PRIMARY KEY,
  doc_type    VARCHAR(32),  -- test_case_sample / test_spec / domain_glossary
  content     TEXT,
  embedding   VECTOR(1536), -- pgvector
  metadata    JSONB,
  created_at  TIMESTAMP DEFAULT now()
);
```

## 4. 核心模块设计

### 4.1 需求理解模块

职责:把非结构化需求转成结构化 JSON,作为下游生成的输入。

Prompt 设计要点:
- 明确角色:"你是一名资深测试架构师"
- 要求输出严格 JSON(用 JSON Schema 约束字段),避免下游解析失败
- 若需求信息不足,要求模型主动列出"待澄清问题"而不是编造

示例输出结构:
```json
{
  "feature_points": ["用户可以通过手机号+验证码登录", "登录失败超过5次锁定账号10分钟"],
  "business_rules": ["验证码有效期5分钟", "同一手机号1分钟内只能发送1次验证码"],
  "edge_cases": ["验证码过期后重新发送", "手机号格式错误", "并发请求验证码接口"],
  "open_questions": ["锁定期间是否允许找回密码?"]
}
```

### 4.2 RAG 检索模块

- 检索对象:历史高质量用例样本、公司测试规范文档、领域术语表
- 检索时机:生成用例前,基于需求关键词/功能点做相似度检索,取 top-k 作为 few-shot 示例
- 一期可先用简单的关键词+embedding 混合检索,不需要复杂的重排序

### 4.3 用例生成引擎

按类型分批生成,而不是一次性让模型生成所有类型,原因:单次 prompt 覆盖面太广会导致遗漏,分类生成可以针对性给出该类型的思考框架。

生成类型建议拆分:
1. 正向功能用例(覆盖 feature_points)
2. 边界值/等价类用例
3. 异常/容错用例(覆盖 edge_cases)
4. 兼容性用例(如需要,可配置开关)

每类用例生成后统一走 Schema 校验(字段完整性),校验失败自动重试(最多2次)。

### 4.4 质检/评审层

一期(MVP)的质检以规则校验为主,AI 打分留到 V2:
- 覆盖率校验:功能点列表 vs 生成用例的 mapping,标记未覆盖的功能点
- 去重校验:标题/步骤相似度过高的用例提示合并
- 人工审核:pending → accepted/rejected/edited,rejected 需填写原因(用于后续优化 prompt)

### 4.5 用例管理层

- 标准 CRUD + 按需求/批次/状态筛选
- 导出:Excel/CSV,兼容常见测试管理工具导入格式
- 追溯:任一用例可查看其来源需求、生成批次、使用的 prompt 版本

## 5. 关键 API 设计(示例)

```
POST /api/requirements                 创建需求
POST /api/requirements/{id}/analyze    触发需求理解(AI)
POST /api/requirements/{id}/generate   触发用例生成(AI),body 可指定生成类型
GET  /api/requirements/{id}/cases      获取该需求下的用例列表
PATCH /api/cases/{id}                  编辑用例 / 更新审核状态
GET  /api/cases/{id}/trace             查看用例追溯信息(来源需求/批次/prompt版本)
POST /api/cases/export                 批量导出
```

## 6. 非功能性设计

- **成本控制**:记录每次调用的 token 用量和费用估算,支持按需求/用户维度做用量统计,避免失控
- **限流与重试**:LLM 调用封装统一的重试(指数退避)+ 超时熔断
- **数据安全**:需求内容可能涉及业务机密,调用商用 API 前评估是否需要脱敏/走企业专属通道(如 Azure OpenAI 私有部署)
- **Prompt 版本管理**:所有 Prompt 模板纳入版本管理,生成批次记录使用的版本号,便于效果对比和回溯

## 7. 里程碑规划

| 阶段 | 内容 | 产出 |
|---|---|---|
| M1(MVP) | 需求录入→AI理解→AI生成→人工编辑→导出 | 可用的单机版工具,验证生成质量 |
| M2 | 引入 RAG 知识库、覆盖率校验、审核工作流 | 生成质量和可用性提升 |
| M3 | 对接外部需求源(如 TAPD)与用例执行平台 | 打通端到端链路,减少人工搬运 |
| M4 | 执行结果反馈闭环、生成效果度量看板 | 持续优化生成效果 |

## 8. 主要风险

- **生成质量不稳定**:需要建立评估集(人工标注的"标准答案"用例),每次改动 Prompt/模型后跑一遍评估集,避免"改了但不知道有没有变好"
- **成本超预期**:大量长文档需求会消耗大量 token,建议对需求长度做分段/摘要预处理
- **人工审核成为瓶子颈**:如果生成量大而审核跟不上,需要设计"高置信度用例免审"之类的分级审核机制(后续迭代)
