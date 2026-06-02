# Project A Final Report: 文献证据链验证系统

**课程**: STA304 Final Project · 大语言模型：从原理到应用  
**方向**: A — 科研智能体功能扩展（Engineering 赛道）— 证据链追踪模块  
**小组**: Group 09  
**基础系统**: DeepScientist（二次开发）  

---

## 1. 项目题目与选择方向

### 1.1 项目题目

**基于 DeepScientist 的文献引用证据链验证系统**

### 1.2 选择方向

**方向 A：科研智能体功能扩展 — 证据链追踪模块**

本方向包含两个递进要求：

**第一层 — 证据链追踪**：使系统输出可追踪、可检查、可复现：
- 记录输入材料与工具输出来源
- 为关键结论标注 evidence ID 并说明来源位置
- 区分三类内容：明确支持 / 合理推断 / 证据不足
- 在 QQ 真实交互中展示该功能
- 至少 5 个测试案例，含 1 个边界案例

**第二层 — 文献引用语义验证**：对 Agent 报告中引用的论文声明进行自动查证：
- 接入第三方文献 API（Semantic Scholar / arXiv / Crossref）核实引用是否真实存在
- 实现红黄绿三色评分机制（🟢 原文支撑 / 🟡 无法确认 / 🔴 原文反驳）
- 生成可审计的 evidence chain 表格，每一条 claim 对应一条 evidence 记录

---

## 2. 选择的基础系统

**DeepScientist**（https://github.com/ResearAI/DeepScientist）——一个本地优先的自主科研工作室系统，管理长期研究 workflow。

**选用理由**：
- 现有 QQ connector 支持真实多模态消息交互
- MCP server framework 支持自定义工具注册
- Quest workflow engine 支持 skill 编排
- Claude CLI runner 提供 LLM 调用基础设施
- 开源 MIT 协议，允许二次开发

**我们的改造范围**：新建 4 个 Python 模块（claim_extractor, semantic_verifier, traffic_light, factcheck_render）+ 1 个 Skill 文件（crossdisc_idea）+ 修改 3 个框架文件（mcp/server.py, prompts/builder.py, pyproject.toml）。其余为框架原有组件。

---

## 3. 问题定义

### 3.1 核心痛点

科研 Agent（如 DeepScientist、OpenClaw）能够生成看似专业的报告，但用户面临三个无法回答的问题：

1. **哪些结论来自真实材料？** — 引用不可追溯，无法复现验证
2. **哪些只是模型推断？** — LLM 可能生成虚构引用（hallucination），缺乏自动检测
3. **哪些完全没有证据？** — 报告措辞强度可能与证据不匹配

### 3.2 具体问题实例

| 问题 | 影响 |
|------|------|
| 引用标注全靠 LLM 自觉 | 报告中引用来源无机器可验证的 ID 体系 |
| 缺乏证据完整性检查 | 无法自动判断"被引文献是否真实存在" |
| 报告措辞与证据脱节 | LLM 在证据不足时仍使用 "perfectly matches" 等强措辞 |
| 多模态输入无结构化记录 | QQ 图片/PDF 无元数据索引，无法按 quest 维度检索 |

### 3.3 研究目标

构建一个**可审计、可追溯的文献证据链验证系统**，使 Agent 的每一条结论都能通过以下链路被验证：

> 输入材料 → 结构化 evidence ID → 第三方 API 验证 → 🟢🟡🔴 红黄绿评分 → 自动化审计

---

## 4. 系统设计

### 4.1 整体架构

```
┌──────────┐    ┌───────────────┐    ┌──────────────┐    ┌───────────────┐
│ QQ 用户   │ →  │ crossdisc_idea│ →  │ parse_pdf    │ →  │ verify_claim  │
│ 上传 PDF  │    │ Skill         │    │    (PyPDF2)  │    │ ×N (S2/arXiv/ │
└──────────┘    └───────────────┘    └──────────────┘     │    Crossref)  │
      ↑                                                   └───────┬───────┘
      │                                                           ↓
      │              ┌───────────────────┐    ┌───────────────────────┐
      │              │ render_report     │ ←  │ score_batch           │
      │              │ 彩色 Markdown 表格 │    │🟢🟡🔴 traffic_light │
      │              └─────────┬─────────┘    └───────────────────────┘
      │                        ↓
      │              ┌───────────────────────┐
      │   QQ 返回     │ artifact__record +   │
      └──────────────│ memory__write         │
                     └───────────────────────┘
```

### 4.2 流水线详解

**Phase 0 — PDF 解析 (parse_pdf)**：PyPDF2 提取文本，正则定位参考文献段（`REFERENCES` heading + 首个 `[` 分隔），按 `[1]...[N]` 或 `[Author, Year]` 格式拆分条目，Unicode 引号匹配提取标题。输出截断保护（MAX_EXTRACTED_CHARS=200000, MAX_RETURNED_CLAIMS=40）。

**Phase 1 — 声明验证 (verify_claim × N)**：对每条 claim 执行三级 fallback 链路：
1. **Semantic Scholar**：按 cited_paper_title 搜索，返回 title+abstract
2. **arXiv**：Title API 匹配，返回 abstract
3. **Crossref**：DOI/title 搜索，返回 abstract

每级失败自动 fallback 到下一级。若 cited_paper_title 为空，从 claim_text 中提取关键词（去引用标记，保留前 7 个实词）构建搜索查询。返回 verdict（supported/not_found/contradicted）+ confidence + evidence。

**Phase 2 — 批量评分 (score_batch)**：对所有 VerificationResult 执行 7 条评分分支：
| 条件 | 评分 | 信号 |
|------|------|------|
| verdict=supported, confidence≥0.7 | 🟢 Green | 原文明确支撑 |
| verdict=supported, confidence<0.7 | 🟡 Yellow | 低置信度支撑 |
| verdict=not_found | 🟡 Yellow | 无法在原文验证 |
| verdict=contradicted, confidence≥0.7 | 🔴 Red | 原文明确反驳 |
| verdict=contradicted, confidence<0.7 | 🟡 Yellow | 低置信度反驳 |
| evidence为空且无cited_paper | 🟡 Yellow | 无可验证来源 |
| 异常/超时 | ⚪ N/A | 验证失败 |

批次总分：🟢≥80% → PASS, 🔴≥30% → FAIL, 🟡≥80% → WARN, 否则 FAIL。

**Phase 3 — 报告渲染 (render_report)**：生成三部分 Markdown——
- Summary 表（🟢🟡🔴 计数 + PASS/WARN/FAIL）
- Per-Claim 详情卡（判决 + 置信度 + 引用原文摘录）
- Evidence Chain 表格（E00X → C00X 映射，含 verdict 与 traffic light）

**Phase 4 — 证据留存**：artifact__record 持久化完整 FactCheckResult JSON（含所有 VerificationResult 和 ScoredClaimResult），memory__write 写入 episodes 记忆供后续 quest 参考。

### 4.3 核心数据结构

流程中传递三个核心 dataclass：

```
Claim(text, cited_paper_title, claim_id)
  → VerificationResult(claim_id, verdict, confidence, evidence, source)
    → ScoredClaimResult(claim_id, traffic_light, ...)
      → FactCheckResult(claims[], score, summary_stats, ...)
```

claim_id 格式为 `C{NNN}`，在全流程中透传，保证每一条 claim 从 parse 到 evidence chain 全程可追踪。

### 4.4 证据链数据结构

所有证据以 `E{NNN}` 格式存入 `evidence_store.json`：

| 证据类型 | ID 格式 | 内容 | 示例 |
|---------|---------|------|------|
| QQ 文本消息 | E001 | 消息文本 + 发送者 + 时间戳 + SHA256 | "请分析这篇论文" |
| QQ 图片附件 | E001-img | 文件名 + 尺寸 + 格式 + SHA256 | 800×600 PNG |
| QQ PDF 附件 | E001-pdf | 文件名 + 页数 + SHA256 + 文本 sidecar | 14 pages, 80KB text |

`audit_report()` 自动扫描报告中的 `[E001]`、`[E001-img]`、`[E001-pdf]` 引用，交叉验证 evidence_store。

### 4.5 强制合同机制

为确保 Agent 不绕过工具链，实施了双层强制机制：

**Layer 1 — SKILL.md (State Machine)**：Phase 5 定义为 5 状态线性管道（Score → Render → Record → Memory → Deliver），每个状态有 exit check，不通过不得进入下一状态。

**Layer 2 — prompts/builder.py (HARD STOP RULE)**：
```
MUST call score_batch exactly once — do NOT compute PASS/WARN/FAIL manually.
MUST call render_report — do NOT hand-write the factcheck table.
MUST call artifact__record and confirm status is "ok".
MUST call memory__write after report generation.
HARD STOP RULE: if any mandatory tool call above is missing,
do not finalize the answer.
```

---

## 5. 测试样例

### 5.1 自动化测试覆盖

| 测试模块 | 数量 | 负责人 |
|----------|------|--------|
| test_connector_evidence.py | 6 | C |
| test_evidence_chain.py | 10 | A |
| test_evidence_audit.py | 14 | B |
| test_factcheck.py | 6 | A |
| test_traffic_light.py | 24 | B |
| test_factcheck_integration.py | 10 | C |
| test_prompt_builder.py | 69 | A |
| **总计** | **139** | **全部通过** |

### 5.2 真实 Quest 验证（6 个学科）

| Quest | 学科领域 | 论文主题 | Claims | verify_claim | 评分 | 工具合规 |
|-------|---------|---------|--------|-------------|------|---------|
| 027 | ML/联邦学习 | pFedAFM | 40 | 85 | 🟢17 🟡18 🔴5 FAIL | 6/6 ✅ |
| 028 | 医学教育 | Subinternship Directors | 8 | 27 | 🟢1 🟡6 🔴1 FAIL | 6/6 ✅ |
| 029 | 计算化学 | DFT Metal Clusters | 1 | 7 | 🟢1 🟡0 🔴0 PASS | 6/6 ✅ |
| 030 | 优化理论 | SGD Convergence | 40 | 105 | 🟢10 🟡28 🔴2 FAIL | 6/6 ✅ |
| 031 | 引力波物理 | LIGO PEMcheck | 40 | 94 | 🟢2 🟡37 🔴1 FAIL | 6/6 ✅ |
| 032 | ML 综述 | Federated Learning Survey | 1 | 5 | 🟢0 🟡1 🔴0 WARN | 6/6 ✅ |

**总计**：996 个 events，323 次 verify_claim 调用，36/36 强制工具调用全部完成。

### 5.3 边界案例覆盖

| 边界案例 | Quest | 说明 |
|---------|-------|------|
| 极低 claim 提取量 | 029 | 仅 1 条 claim，系统正常产出 PASS 报告 |
| 高度不确定率 | 031 | 37/40 🟡，系统诚实标注并解释原因 |
| 跨学科引用格式 | 031 | LIGO 物理引用格式特殊，verifier 返回 not_found |
| 论文内部数学证明 | 027/030 | 定理/引理无法通过 API 验证，标记为 not_found |
| 多引用标记 | 027 | `[20]–[24]` 连字符引用正确解析 |
| Fake ID 检测 | 测试 | `test_audit_detects_fake_image_id` — E999-img 被正确标记 |

---

## 6. 失败案例分析

### 6.1 Verifier 假阳性（跨学科标题匹配偏差）

**案例**：Quest 031 (LIGO) — C036（GW190707_093326 事件）被标记为 🔴 contradicted

**原因**：Semantic Scholar 的标题搜索将 `GW190707_093326`（LIGO 事件编号）匹配到了另一篇有重叠作者名的 LIGO 论文，导致 polarity detection 误判。

**系统如何处理**：报告 §6 Caveats 明确标注 "almost certainly a false negative — the verifier matched a different LIGO paper with overlapping author names"。

### 6.2 抽象级验证的局限

**案例**：Quest 030 (SGD) — C018 和 C031 被标记为 🔴

**原因**：验证器只有 abstract 级别的访问权限。数学论文中 "exponential convergence for PL-functions under heavy-ball" 这类声明需要全文验证，abstract 通常不包含足够细节。

**系统如何处理**：报告 §1 中明确区分 "abstract-only verification" 和 "manual review recommended"。

### 6.3 PDF Parser Fallback（医学论文不在 arXiv）

**案例**：Quest 028 (医学教育) — `parse_pdf` 提取了 0 条结构化 claim

**原因**：医学教育领域论文通过 PubMed/MedLine 索引而非 arXiv。PDF 文本可提取（PyPDF2 成功），但引用格式（`[Lyss-Lerman et al. 2009]` 命名标记）与 IEEE 数字标记 `[1]` 不同，导致 claim_extractor 的引用段解析无法匹配。

**系统如何处理**：SKILL.md Phase 0 有明确的 pdf-fallback 指令——如果 `parse_pdf` 返回空列表，Agent 自动退回到 `bash_exec` 手动提取。report 中 extraction_method 标注为 `bash_fallback`，证据链表格中标注为 ⚪。全流程仍然完成（8 claims 验证 + 6/6 工具合规）。

### 6.4 Agent 绕过工具链（中期版本）

**案例**：早期 quest 027 中，Agent 虽然产出了看起来格式正确的报告，但实际上只调用了 10 次 verify_claim（40 claims 中），完全没有调用 score_batch 和 render_report——所有评分都是 LLM 手工做的。

**修复策略迭代**：
1. SKILL.md 中添加 `MUST` + 代码示例 → Agent 仍然绕过
2. SKILL.md 重写为 5-State Machine + exit checks → 部分改善
3. prompts/builder.py 添加 HARD STOP RULE → **彻底修复**（36/36 合规）

此迭代过程证明了 "prompt 级建议" 与 "框架级强制" 之间的差距，是 Agent 系统设计的重要经验。

---

## 7. 局限性与未来改进

### 7.1 当前局限

| 局限 | 影响 | 严重度 |
|------|------|--------|
| Abstract-only 验证 | 大部分 🟡 不确定需要在全文级别才能解决 | 中 |
| PyPDF2 对扫描版 PDF 支持弱 | 纯图像 PDF 需要 OCR 预处理 | 低 |
| Verifier 假阳性（标题匹配偏差） | 约 5-10% 的 🔴 可能是误报 | 中 |
| API 依赖 | 无网络环境下完全不可用 | 低 |
| 视频/音频不支持 | 仅处理文本、图片、PDF | 低 |

### 7.2 未来改进

1. **Full-text 验证**：集成 arXiv open-access 全文检索，降低 uncertain 比例
2. **本地模型 fallback**：集成 Ollama + sentence-transformers，减少对外部 API 依赖
3. **Claim 质量改进**：将 `claim_extractor` 的 LLM 抽取替换为结构化 NLP pipeline
4. **多 Connector 支持**：将事实核查能力扩展到 WeChat、Discord 等 connector
5. **缓存与限速**：为 verify_claim 增加结果缓存层，避免重复 API 调用

---

## 8. 个人与小组贡献说明

**廖苗懿 — Person A：工具层**

负责 FactCheck 链条的 PDF 入口与文献验证核心。

- **`claim_extractor.py`**：PyPDF2 文本提取、参考文献段定位（heading pattern 匹配 + bracket 切割）、Unicode 引号匹配提取标题、MAX_EXTRACTED_CHARS/MAX_RETURNED_CLAIMS 截断保护、PDFExtractionError 异常体系
- **`semantic_verifier.py`**：Semantic Scholar → arXiv → Crossref 三级 fallback 验证链、`_build_search_query()` 去引用标记保留前 7 实词、`_best_evidence_for_title()` fallback 关键词搜索
- **`prompts/builder.py`**：crossdisc_idea 强制合同注入（HARD STOP RULE：score_batch、render_report、artifact__record 不可绕过）
- **证据链核心**：evidence-chain tracking store、API 与 runner instrumentation
- **测试**：`test_factcheck.py` (6)、`test_evidence_chain.py` (10)、`test_prompt_builder.py` (69)

**熊筱瑜 — Person B：评分渲染 + 全部测试**

负责 RYG 评分算法、Markdown 报告渲染、MCP 工具注册，以及全部 quest 实际运行。

- **`traffic_light.py`**：`score_verification()` per-claim 🟢🟡🔴 判定 + `score_batch()` 批次 PASS/WARN/FAIL/N/A 汇总，覆盖 7 条评分分支（supported/not_found/contradicted × confidence 高低 + 空 evidence + 异常）
- **`factcheck_render.py`**：`render_factcheck_markdown()` 彩色表格 + per-claim 详情卡、`render_factcheck_summary()` 摘要
- **`mcp/server.py`**：`build_factcheck_server()` 注册 5 个 MCP tool（parse_pdf, verify_claim, score_batch, render_report, render_summary），dataclass ↔ dict 序列化
- **SKILL.md 迭代**：claim_id 透传修复、Phase 5 重写为 5-State Machine、artifact kind 修正
- **Pipeline 修复**：PDF 参考文献解析修复、全流程 scoring pipeline 打通
- **证据链前期**：evidence chain audit module、prompt 证据协议
- **全部 6 个测试样例 (027-032)**：PDF 选取（跨 6 学科）、quest 运行与调试、output-report + events.jsonl 收集
- **测试**：`test_traffic_light.py` (24)、`test_evidence_audit.py` (14)、`test_connector_evidence.py` (6)

 **刘宇翔 — Person C：入口与集成**

负责 Skill 编排、QQ 多模态证据入口、daemon 集成与 memory schema。

- **`crossdisc_idea/SKILL.md`**（109 行新增/修改）：
  - 5-Phase pipeline 编排（parse → verify → score → render → deliver）
  - Phase 5 重写为 5-State Machine（Score→Render→Record→Memory→Deliver），每步含 exit checks
  - Phase 0 pdf-fallback 指令：parse_pdf 失败时自动退至 bash_exec 手动提取
  - C→E evidence ID 映射规则（C001→E001），确保报告引用可被 audit_report 验证
  - wording discipline 措辞规范：4 组强弱替换对照表（perfectly matches→partially aligns 等）
  - memory schema 定义：`kind="episodes"`（修复单复数报错）、结构化 metadata 字段
  - evidence chain 表格模板：Evidence ID + Claim ID + Source + Extraction Method + Verdict + Traffic Light

- **QQ 多模态证据录制**（`evidence_chain.py`, `daemon/app.py`）：
  - `record_connector_event()`：connector_text（E00X）、connector_image（E00X-img，含 SHA256 + 尺寸 + 格式）、connector_file（E00X-pdf，含页数 + SHA256 + PyPDF2 文本 sidecar）三类证据条目
  - `_extract_pdf_text_sidecar()`：自动提取 PDF 全文至 `.ds/evidence/sidecars/`，80KB+ 文本
  - `_pdf_metadata()`：PDF 元数据提取（页数、SHA256、文件大小）
  - evidence recording hook 注入 daemon app.py 的 connector 消息路由链路

- **daemon 集成与 Runner 修复**（`runners/claude.py`, `runners/simple_cli.py`）：
  - MCP server PATH 过滤（移除系统 Python 路径，避免 MCP 进程重复）
  - TEMP/TMP/TMPDIR 重定向至 DS_HOME（修复磁盘满导致 MCP 死锁）
  - `--strict-mcp-config` 添加（禁用 Claude CLI 自动 MCP 发现）
  - `pythonw.exe` → `python.exe` 校正（Windows daemon 后台进程修复）
  - stdin 提前写入修复（Claude CLI ≥2.1.152 的 3s 输入超时导致 Runner 崩溃）
  - `artifact.interact` 异步 dispatch（45s 线程超时，修复 QQ connector 慢响应阻塞 MCP stdio）
  - QQ connector profile 重复投递修复

- **`prompts/builder.py`**（C 协助 A/B 联调）：
  - 图片/PDF attachment `raw_binary_path` 从 hidden 改为可见
  - attachment_handling_rule 更新：图片 MUST Read、PDF MUST PyPDF2 提取

- **证据链审计扩展**（`evidence_audit.py`）：
  - 扩展 `_EVIDENCE_ID_PATTERN` 支持 `E\d+-pdf` 格式

- **测试**：`test_connector_evidence.py` (6)、`test_factcheck_integration.py` (10)

### 交叉协作

- **Phase 5 强制执行**：A 提供 HARD STOP RULE (builder.py)，B 将 Phase 5 重写为 5-State Machine，C 提供 memory/artifact schema —— 三层共同保证 Agent 不绕过工具链
- **证据链系统**：A 提供存储层与 runner 埋点，B 提供审计脚本与 prompt 协议，C 提供 QQ 多模态入口
- **全流程打通**：B 主导 quest 实际运行、失败分析、pipeline 迭代修复
