# Prompt 效果验证

用于验证 `prompts/` 目录下的模板在真实需求上的生成效果,是 `docs/DESIGN.md` 中"需求理解 + 分类型用例生成"两个模块的可运行验证环境。

## 目录结构

```
eval/
  metrics.py          # 召回率/覆盖率的模糊匹配计算
  dataset/            # 评测用需求样例,每条包含人工标注的 golden 结果
  run_eval.py         # 主脚本
  rescore.py          # 用已缓存的 raw_content 重新计算指标(迭代 metrics.py 时用,不重新调用 API)
  results/            # 运行后生成,保存每个阶段的原始输出,供人工抽查
```

LLM 调用客户端、prompt 加载、LLM 输出结构校验这三块已经迁移到 `app/llm/`,由本评测脚本和 `app/` 后端服务共用,避免逻辑分叉。

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env   # 填入 OPENAI_API_KEY 或 ANTHROPIC_API_KEY

# 干跑(不消耗真实 API 额度,验证 pipeline 逻辑本身是否正确)
python eval/run_eval.py --mock

# 真实调用
python eval/run_eval.py

# 只跑其中一条需求
python eval/run_eval.py --dataset req_001_coupon.json
```

## 输出解读

终端会打印每条需求的:
- **需求理解阶段**:`feature_point_recall_rate` / `edge_case_recall_rate` —— AI 拆解出的功能点/异常场景,相对人工标注 golden 数据的召回率(模糊匹配,阈值 0.45)
- **用例生成阶段**(functional/boundary/exception 各一行):
  - `schema通过率`:生成的用例里有多少条能通过 pydantic 结构校验
  - `覆盖率`:上一阶段拆出的功能点/业务规则/异常场景,有多少条被生成用例的 `covers` 字段引用到
  - token 用量与耗时

`eval/results/<req_id>/00_report.json` 里有完整报告,包含具体"漏掉了哪些功能点/场景"的清单;`01_analysis_raw.json`、`02_*_raw.json`、`03_final_cases.json` 分别是每个阶段的原始 prompt、原始输出和最终解析出的用例列表,建议生成后人工抽查 `03_final_cases.json` 里用例的实际可读性和可执行性 —— 这两项无法靠脚本自动判断。

## 指标的局限性

召回率/覆盖率用的是字符串相似度模糊匹配(`difflib`),不是语义匹配,只能作为快速回归的"预警信号"(比如改了 Prompt 后覆盖率骤降,说明大概率有问题)。真正判断生成用例质量,仍需要人工抽查 `results/` 里的具体内容。后续如果要提升准确度,可以考虑换成 embedding 相似度或 LLM-as-judge,但会引入额外的调用成本。

## 调优建议

1. 先用 `--mock` 确认 pipeline 和指标计算逻辑没有 bug。
2. 用真实 API 跑一遍三条样例需求,人工检查 `03_final_cases.json`。
3. 根据 `missed_feature_points` / `missed_source_items` 里列出的漏点,判断是 Prompt 指令不够清晰,还是需求本身信息不足。
4. 调整 `prompts/*.jinja2` 后重新跑,对比覆盖率/召回率变化,同时人工确认用例质量没有因为"为了刷覆盖率"而生成一堆凑数的低质量用例。
5. 确认效果稳定后,把评测数据集扩充到 10~20 条覆盖不同业务领域的需求,形成常态化回归集。
