# Defense Technical Guide — 文献证据链验证系统

## 快速索引用表

| 如果被问到… | 看这里 |
|------------|--------|
| 整体架构怎么设计的？ | §1 → sources below |
| PDF 是怎么解析的？ | `claim_extractor.py:51-91` 和 `claim_extractor.py:202-226` |
| 引用是怎么逐条验证的？ | `semantic_verifier.py:178-209` + 三级 fallback（line 44, 59, 72） |
| 🟢🟡🔴 是怎么评出来的？ | `traffic_light.py:10-83`（7 分支）+ `__init__.py:62-69`（总分公式） |
| 报告是怎么渲染的？ | `factcheck_render.py:38-78` |
| Agent 是怎么调工具的？ | `SKILL.md:146-264`（Phase 5 State Machine） |
| Prompt 是怎么强制 Agent 的？ | `builder.py:278-290`（HARD STOP RULE） |
| 证据链是怎么录制的？ | `evidence_chain.py:407-560`（record_connector_event） |
| MCP 工具有哪些？ | `server.py:2644-2800`（build_factcheck_server） |
| 四个 dataclass 是什么关系？ | `factcheck/__init__.py:11-70` |
| Agent 是怎么"打不过就绕过"的？ | §4（Compliance Journey） |

---

## §1. 完整调用链路（从 QQ 消息到报告输出）

```
1. QQ 用户发送 PDF + "/crossdisc_idea"
   → daemon/app.py:submit_user_message() 接收消息

2. Claude CLI runner 启动 → 加载 crossdisc_idea/SKILL.md
   → 注入 prompts/builder.py:278-290 (HARD STOP RULE)

3. Phase 1: parse_pdf(pdf_path)
   → claim_extractor.py:202  parse_pdf()
     → line 51  _read_pdf_like_text() — PyPDF2 提取文本
     → line 94  _split_main_and_references() — 正则定位 REFERENCES 段
     → line 107 _parse_reference_index() — 解析 [1]...[N] 引用，用 Unicode 引号匹配标题
     → line 202 parse_pdf() — 按句子 split，_looks_like_claim() 筛选
     → 返回 list[Claim] (最多 40 条)

4. Phase 2: verify_claim(claim_text, cited_paper_title) × N 次
   → semantic_verifier.py:178  verify_claim()
     → line 82  _best_evidence_for_title() 三级 fallback:
       (1) line 44  _search_semantic_scholar() — 免费 API, 200M+ papers
       (2) line 72  _search_arxiv_abstract() — arXiv Title API
       (3) line 59  _search_crossref_title() — Crossref DOI/title search
     → line 159 _heuristic_verdict() — 词法重叠 + 极性检测
     → 返回 VerificationResult(verdict, confidence, evidence_snippet)

5. Phase 3: score_batch(results)
   → traffic_light.py:88  score_batch()
     → line 10  score_verification() — 7 分支 RYG 规则
     → 返回 FactCheckResult(score, green/yellow/red counts)

6. Phase 3: render_report(batch_result)
   → factcheck_render.py:38  render_factcheck_markdown()
     → line 23  render_claim_card() — 每 claim 一张卡片
     → 返回 彩色 Markdown 字符串

7. Phase 5 State Machine: 
   STATE_1 → score_batch (exit check: score 值合法)
   STATE_2 → render_report (exit check: ≥200 chars, 含 🟢🟡🔴)
   STATE_3 → artifact__record (exit check: status=ok, body≥500 chars)
   STATE_4 → memory__write (exit check: markdown≥500 chars)
   STATE_5 → artifact__interact → QQ 发送
```

---

## §2. 四个核心 dataclass（`factcheck/__init__.py:11-70`）

**你一定得能画在黑板上的数据流图：**

```
Claim (line 12)                     ← parse_pdf 输出
├── claim_id: str          "C001"
├── claim_text: str        "Attention improves BLEU by 2.4"
├── citation_markers: []   ["[Smith 2023]"]
└── cited_paper_title: str "Attention Is All You Need"

         ↓ verify_claim()

VerificationResult (line 22)        ← verify_claim 输出
├── claim_id: str
├── verdict: str     "supported"|"contradicted"|"not_found"|"uncertain"
├── confidence: float 0.0–1.0
├── evidence_level: str   "abstract_only" (当前版本)
├── evidence_snippet: str 原文中支撑/反驳的句子
└── notes: str

         ↓ score_verification()

ScoredClaimResult (line 36)          ← traffic_light 输出
├── color: str    "green"|"yellow"|"red"
├── label: str    "正确"|"不确定"|"错误"
└── rationale: str

         ↓ score_batch() 聚合

FactCheckResult (line 50)            ← 最终聚合结果
├── total_claims, green_count, yellow_count, red_count
├── results: list[ScoredClaimResult]
└── score (property): PASS|WARN|FAIL|N/A
    → 公式: line 62-69
    → red_count > 0 → FAIL
    → yellow > total*0.3 → WARN
    → else → PASS
```

---

## §3. RYG 评分引擎（`traffic_light.py:10-83`）

**你必须记牢的 7 条规则**（每条 1 行记忆法）：

| Condition | Color | 记忆口诀 |
|-----------|-------|---------|
| supported + conf≥0.7 | Green | "高置信支撑 = 绿" |
| supported + conf<0.7 | Yellow | "低置信支撑 = 黄" |
| contradicted + conf≥0.7 | Red | "高置信反驳 = 红" |
| contradicted + conf<0.7 | Yellow | "低置信反驳 = 黄" |
| uncertain (any conf) | Yellow | "不确定 = 黄" |
| not_found (any conf) | Yellow | "找不到 = 黄" |
| unknown verdict | Yellow | "未知 = 黄（fallback）" |

**Batch 总分公式**（`__init__.py:62-69`）：
- total=0 → N/A
- red>0 → FAIL（只要有一条红就 fail）
- yellow > total*0.3 → WARN（超过 30% 不确定就 warn）
- 其他 → PASS

---

## §4. Agent Compliance Journey（答辩亮点——我们学到了什么）

**4 轮迭代：从 0/6 到 36/36**

| v | 做法 | 结果 |
|---|------|------|
| v1 | SKILL.md 写 "please call score_batch" | Agent 完全绕过了 |
| v2 | SKILL.md 写 "MUST call" + 给代码示例 | 只调了 10/40 verify，0 score，0 render |
| v3 | Phase 5 重写为 5-State Machine，每步加 exit check | 部分改善，但仍可绕过 |
| v4 | **prompts/builder.py:278-290 注入 HARD STOP RULE** | **36/36 强制工具全部完成** |

**核心教训**（答辩加分句）：
> SKILL.md is *advisory*. builder.py HARD STOP RULE is *mandatory*.
> Agent system design must distinguish between the two.

**HARD STOP RULE 位置**：`prompts/builder.py:278-290`
- 当 skill_id == "crossdisc_idea" 时，注入 "FactCheck Execution Contract" 段落
- 8 条 MUST 规则 + 最后一条 "HARD STOP RULE: if any mandatory tool call above is missing, do not finalize"

---

## §5. PDF 解析引擎（`claim_extractor.py`）

**核心函数调用链**：
```
parse_pdf(pdf_path) → line 202
  → _read_pdf_like_text(path) → line 51 (PyPDF2)
  → _split_main_and_references(text) → line 94
  → _parse_reference_index(references) → line 107
  → _split_sentences(main_text) → line 166
  → _looks_like_claim(sentence) → line 174
```

**关键参数（一定会被问到）**：
- `MAX_EXTRACTED_CHARS = 200_000`（line 8）— 防止 PDF 提取结果超过上下文窗口
- `MAX_RETURNED_CLAIMS = 40`（line 9）— 超出截断
- `MIN_READABLE_RATIO = 0.45`（line 10）— 低于此值抛 PDFExtractionError

**参考文献段检测**（line 18-21）：
- 正则 `/REFERENCES|BIBLIOGRAPHY/` + 紧接着 `[` — 定位参考文献段起始
- 按 `[N]` 或 `[Author,Year]` 切割每个引用条目
- 用 Unicode 引号（`""''「」` 等）提取标题

**Fallback 机制**（答辩加分项）：
- Quest 028（医学教育）：parse_pdf 返回 0 条 claim → Agent 自动回退 `bash_exec` 手动提取
- extraction_method 标记为 `bash_fallback` 写入 evidence table

---

## §6. 语义验证引擎（`semantic_verifier.py`）

**`verify_claim()` → line 178 的调用链**：
```
verify_claim(claim_text, cited_paper_title)
  → _best_evidence_for_title(title, timeout, fallback) → line 82
    → _search_semantic_scholar(title) → line 44 (200M+ papers, free)
    → _search_arxiv_abstract(title) → line 72 (2.4M open-access)
    → _search_crossref_title(title) → line 59 (150M+ records)
  → _heuristic_verdict(claim_text, evidence_text) → line 159
```

**验证器如何处理空标题**（重点！）：
- line 144  `_build_search_query(claim_text)` — 从 claim 文本中提取关键词
- 去引用标记，保留前 7 个实词，构建搜索查询
- 因此即使 cited_paper_title 为空，验证器仍能工作

**置信度是 heuristic（不是 ML 模型）**：
- `confidence > 0.8` — 证据文本中出现 claim 的核心词
- `confidence < 0.3` — 词法重叠 < 3 个 token
- 这解释了为什么 abstract-only 模式下大部分结果是 uncertain

---

## §7. MCP 工具注册（`mcp/server.py:2644-2800`）

```
build_factcheck_server(context) → line 2644
  注册 5 个 MCP tool:
    1. parse_pdf(pdf_path) → list[Claim]
    2. verify_claim(claim_text, cited_paper_title, claim_id?) → VerificationResult
    3. score_batch(results, quest_id, source_pdf) → FactCheckResult
    4. render_report(batch_result) → str (Markdown)
    5. render_summary(batch_result) → str (one-line)
```

**MCP 工具在 system prompt 中的名字**：
- `mcp__factcheck__parse_pdf`
- `mcp__factcheck__verify_claim`
- `mcp__factcheck__score_batch`
- `mcp__factcheck__render_report`
- `mcp__factcheck__render_summary`

**claim_id 映射合约**（`SKILL.md:49-58`）：
- verify_claim 现在支持传入 `claim_id` 参数（person A 加的功能）
- 传入后返回的 VerificationResult.claim_id 就是正确的
- 如果忘传，需要手动 `vr.claim_id = claim.claim_id`

---

## §8. 强制合同机制（双保险）

```
Layer 1 — SKILL.md Phase 5 State Machine (line 146-264)
  5 状态严格串行: Score → Render → Record → Memory → Deliver
  每状态有 exit check，不通过不能前进
  禁止回退到之前的状态

Layer 2 — builder.py HARD STOP RULE (line 278-290)
  注入到 system prompt 的硬性约束
  "if any mandatory tool call is missing, do not finalize"
  这是 Agent 无法绕过的根本原因
```

---

## §9. 证据链录制（`evidence_chain.py:407-560`）

**三类证据条目**：
```
E001      connector_text     → QQ 文本消息 + sender_id + SHA256
E001-img  connector_image    → 图片: 尺寸 + 格式 + SHA256
E001-pdf  connector_file     → PDF: 页数 + SHA256 + text sidecar
```

**审核正则**（`evidence_audit.py:31`）：
```python
_EVIDENCE_ID_PATTERN = re.compile(r"\[(ev_[^\]]+|E\d+(?:-img|-pdf)?)\]")
```
检测 `[E001]`, `[E001-img]`, `[E001-pdf]` 三种格式。

---

## §10. 预期答辩问题 & 应答模板

**Q1: "你们的验证器准确吗？"**
> 当前是基于词法重叠的 heuristic 评分，不是 semantic entailment 模型。
> 所以我们没有宣称"精确"，而是诚实地标了大部分为 🟡 uncertain。
> Abstract-only 是主要限制——这在 Limitations 中明确写了。

**Q2: "为什么不用 ChatGPT/Claude 做验证？"**
> 用 LLM 验证 LLM 的输出会引入循环依赖——无法判断验证结果本身是否可靠。
> 我们选择的是实时 API 查询（Semantic Scholar 等），这些是确定的、可复现的。

**Q3: "你们的贡献 vs. DeepScientist 原有功能？"**
> 我们新建了 4 个 Python 模块 (factcheck/) + 1 个 skill 文件，修改了 3 个框架文件。
> QQ connector、MCP framework、quest engine 是框架原有的。
> 我们的增量是"证据链 + 文献验证 + RYG 评分 + 跨学科 idea 生成"。

**Q4: "你（C）具体做了什么？"**
> 我是 Person C，负责三层：
> (1) 入口层：crossdisc_idea SKILL.md 的 5-Phase pipeline 编排 + State Machine
> (2) 证据层：QQ 多模态证据录制（text/image/PDF）、memory schema、evidence chain 表格模板
> (3) 集成层：daemon 集成、runner 修复（MCP PATH 过滤、stdin 时序、interact 超时）、16 个测试用例
> 具体代码位置见 §11。

**Q5: "HARD STOP RULE 是怎么工作的？"**
> 它是 Person A 写在 `prompts/builder.py:278-290` 的强制合同。
> 当 Agent 启动 crossdisc_idea skill 时，这段文本被注入 system prompt。
> 它告诉 Agent："如果 score_batch、render_report、artifact__record、memory__write 中任何一步缺失，不要结束回答。"
> 这是我们把合规性从 0/6 提升到 36/36 的关键。

**Q6: "Phase 2 的 Scoring 规则为什么是 conf≥0.7？"**
> 这个阈值是 Person B 在 `traffic_light.py:10-83` 中根据实证调出来的。
> 24 个单元测试覆盖了所有 verdict × confidence 组合。
> 0.7 是 experiments-based 的经验阈值，不是随意选的。

---

## §11. 文件速查表（把文件打开就能讲）

```
src/deepscientist/factcheck/__init__.py          四个 dataclass，核心数据流
src/deepscientist/factcheck/claim_extractor.py    PDF 解析，parse_pdf()
src/deepscientist/factcheck/semantic_verifier.py  三级 API 验证，verify_claim()
src/deepscientist/factcheck/traffic_light.py      7-branch RYG 评分
src/deepscientist/factcheck/factcheck_render.py   Markdown 渲染
src/deepscientist/mcp/server.py:2644              MCP 5 工具注册
src/deepscientist/prompts/builder.py:278           HARD STOP RULE 注入点
src/skills/crossdisc_idea/SKILL.md:146            Phase 5 State Machine
src/deepscientist/evidence_chain.py:407           QQ 多模态证据录制
src/deepscientist/evidence_audit.py:31            audit_report 正则
```

---

## §12. 关键数据（答辩随时引用）

| 数据 | 数值 |
|------|------|
| 测试总数 | 139 / 100% pass |
| Quest 总数 | 6 个，跨 6 学科 |
| verify_claim 总调用 | 323 次 |
| 强制工具合规率 | 36/36 |
| 新建模块 | 4 Python + 1 Skill |
| 修改框架文件 | 3 |
| HARD STOP RULE 位置 | builder.py:278-290 |
| State Machine 位置 | SKILL.md:146-264 |
