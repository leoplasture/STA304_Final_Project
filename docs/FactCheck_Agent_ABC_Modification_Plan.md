# FactCheck Agent 下一步修改分工文档

## 1. 背景说明

当前项目已经具备以下基础能力：

- FactCheck 工具模块已经存在，包括 `traffic_light.py`（B，24 tests passing）和 `factcheck_render.py`（B，已完整实现）
- `semantic_verifier.py`（A）和 `claim_extractor.py`（A）已通过 MCP 注册为 `mcp__factcheck__parse_pdf` 和 `mcp__factcheck__verify_claim`
- Agent 入口 skill：`crossdisc_idea/SKILL.md`（C）位于 `skill_order: 55`，编排 5-phase factcheck pipeline
- 项目中已有 evidence chain（A）、memory（B）、artifact service、QQ connector、测试等相关代码
- 系统目标是支持"输入一篇文献，输出跨学科 idea 调研，并通过 FactCheck pipeline 检查结论可靠性"

### 1.1 当前实际运行状态（基于 quest 014 实测）

014 跑通了完整链路，但暴露了以下问题：

| # | 问题 | 严重度 | 归属 |
|---|------|--------|------|
| 1 | Agent 没有调用 B 的 `score_batch` / `render_factcheck_markdown`，自己用 LLM 生成了打分和报告 | 高 | A/C |
| 2 | `claim_id` 映射合约没执行（verify_claim 返回空 claim_id，Agent 没补） | 高 | A/C |
| 3 | Phase 3（Score and Render）被完全跳过 | 高 | A/C |
| 4 | `parse_pdf` 返回 38万~213万字符垃圾数据，Agent 被迫用 34 次 `bash_exec` 手动提取 PDF 文本 | 高 | A |
| 5 | `mcp__artifact__record` 从未被调用，report 只通过 interact 发送，未写入 evidence store | 中 | A/C |
| 6 | `mcp__memory__write` 报错 `Unknown memory kind: episode`（2 次） | 中 | C |
| 7 | Agent 尝试 `pip install PyPDF2` 失败（bash_exec 不在 venv 中） | 低 | 环境 |
| 8 | 最终报告中 FactCheck 结果（Uncertain/Not Found）与后文措辞（"perfectly matches"、"genuinely novel"）强弱不一致 | 中 | C |
| 9 | 报告缺少 evidence chain 表格、无 git checkpoint、无 quest state 更新 | 低 | A/C |
| 10 | `verify_claim` 3 次调用结果：2 个 uncertain(0.45) + 1 个 not_found(0.0)，abstract-only 搜索基本不可靠 | 中 | A |
| 11 | deepseek-v4-pro 不支持 `system` role，导致 ~80% run 直接崩溃（本次侥幸跑通） | **严重** | 基础设施 |

---

## 2. 总体修改目标

本轮修改的核心目标是：

> 让系统从"LLM 自己写一个看起来像 FactCheck 的报告"，升级为"Agent 调用 FactCheck 工具，生成可审计、可追踪、有红绿灯评分的研究检查报告"。

正确的系统流程：

```text
parse_pdf (MCP tool)
→ extract claims
→ verify_claim (MCP tool)
→ claim_id mapping (Agent 必须做)
→ score_batch (B's traffic_light.py)
→ render_factcheck_markdown (B's factcheck_render.py)
→ mcp__artifact__record (写入 evidence store)
→ final report (嵌入 render 输出)
→ mcp__memory__write (记录 experiment)
→ mcp__artifact__interact (发送 QQ)
```

当前实际流程（014）：

```text
parse_pdf → 返回垃圾数据(2次均超token上限)
→ bash_exec × 34 (手动 zlib 解压 + 正则提取 PDF 文字)
→ verify_claim × 3
→ LLM 自己写 RYG 判断和报告 (跳过 score_batch / render)
→ interact 发送 (跳过 artifact record)
→ memory write 报错
```

本轮需要补上的关键环节：

```text
verify_claim → claim_id mapping → score_batch → render_factcheck_markdown
→ artifact record → evidence chain → memory schema
```

---

# 3. A 同学分工：Agent 主流程修复 + PDF Parser

## 3.1 A 的核心目标

A 负责两件事：
1. Agent 编排逻辑 — 保证 Agent 不绕过 B 的工具链
2. `claim_extractor.py` — 修复 PDF parser 输出质量

## 3.2 A 的具体任务

### A1. 修复 Phase 3 被跳过的问题（与 C 协作，已部分完成）

**已在 `crossdisc_idea/SKILL.md` Phase 3 中修改：**
- 明写 `from deepscientist.factcheck.traffic_light import score_batch, score_verification`
- 明写 `from deepscientist.factcheck.factcheck_render import render_factcheck_markdown`
- 明写 `Do NOT compute scores manually` / `Do not hand-write the table`
- 给出了完整的 4-step 调用代码示例

**A 需要做的：**
- 验证 Agent 在新 skill 指令下确实调用了 `score_batch` 和 `render_factcheck_markdown`
- 如果 Agent 仍然绕过，考虑在 `prompts/builder.py` 的 stage prompt 中硬编码工具调用要求
- SKILL.md 是"建议"，prompt builder 可以做到"强制"——这是 A 的 fallback 手段

### A2. 修复 claim_id 映射（与 C 协作，已部分完成）

**已在 `crossdisc_idea/SKILL.md` Phase 2 中修改：**
- 用 `CRITICAL — MUST DO, NOT OPTIONAL` 标题强调
- 给了明确的代码示例：`vr.claim_id = claim.claim_id`
- 明确写了跳过此步的后果

**A 需要做的：**
- 同 A1，验证 Agent 服从指令
- 可选：在 `verify_claim` MCP tool 的输出中加 `claim_id` 参数支持（让调用方传入，透传回去），降低 Agent 忘记映射的风险

### A3. 修复 PDF parser（高优先级）

当前 `parse_pdf` 返回 38万~213万字符的 PDF 操作符垃圾，导致 Agent 被迫用 34 次 bash_exec 手动提取。根因是 `claim_extractor.py` 对 PDF 的文本提取质量差。

**具体修复方向：**
1. 在 `parse_pdf` 中增加输出截断逻辑：超过 N 条 claims 时只返回前 N 条 + truncated 标记
2. 增加文本清洗：过滤 PDF 操作符、控制字符、非可读内容
3. 如果 PDF 文本提取后仍然是垃圾（可读内容占比 < 阈值），自动 fallback 并返回 error dict 而非天量垃圾
4. 考虑使用 `pdfplumber` 或 `pymupdf` 替换当前的 raw stream 解析

**短期 fallback（本轮可做）：**
- parse_pdf 返回 `{"ok": false, "error": "PDF text extraction failed", "fallback_recommended": true}` 而非垃圾数据
- Agent 看到这个 error 会走 bash_exec fallback（它已经会了），但至少不会先被垃圾数据淹没

### A4. 增加 Agent 层集成测试

建议测试项：

```text
score_batch 调用次数 >= 1
render_factcheck_markdown 调用次数 >= 1
最终报告包含 🟢 / 🟡 / 🔴
最终报告包含 PASS / WARN / FAIL
最终结果保留原始 claim_id
artifact record 调用次数 >= 1 (report 写入 evidence store)
```

可以用 mock/spy 方式检查函数调用次数。

## 3.3 A 的验收标准

| 检查项 | 预期结果 |
|---|---|
| Agent 是否调用 `score_batch` | 是 |
| Agent 是否调用 `render_factcheck_markdown` | 是 |
| Agent 是否保留原始 `claim_id` | 是 |
| 最终报告是否包含 🟢🟡🔴 | 是 |
| 最终报告是否包含 PASS/WARN/FAIL | 是 |
| Agent 是否仍然绕过 Phase 3 写报告 | 否 |
| parse_pdf 是否不再返回超过 50KB 的垃圾数据 | 是 |
| parse_pdf 失败时是否返回明确的 error | 是 |
| Agent 是否调用 `mcp__artifact__record` 写入报告 | 是 |
| verify_claim 返回 uncertain/not_found 时 Agent 是否仍正常产出报告 | 是 |

---

# 4. B 同学分工：FactCheck 工具模块完善

## 4.1 B 的核心目标

B 负责 FactCheck 工具本身的输出规范和对 A/C 的对接支持。B 的 `traffic_light.py` 和 `factcheck_render.py` 已有 24 个测试全过，本轮重点是**确认输出满足最终报告的需求**，而非重写工具。

## 4.2 B 的具体任务

### B1. 确认评分映射表正确性（注意：与 014 报告的映射表不同）

**当前 `traffic_light.py` 的实际映射（来源：`tests/test_traffic_light.py`，24 tests passing）：**

**单条 claim 级别 (`score_verification`)：**

| verdict | confidence | color | label |
|---------|-----------|-------|-------|
| `supported` | ≥ 0.8 | 🟢 green | 正确 |
| `supported` | < 0.8 | 🟡 yellow | 不确定 |
| `contradicted` | ≥ 0.7 | 🔴 red | 错误 |
| `contradicted` | < 0.7 | 🟡 yellow | 不确定 |
| `uncertain` | any | 🟡 yellow | 不确定 |
| `not_found` | any | 🟡 yellow | 不确定 |
| unknown verdict | any | 🟡 yellow | 不确定（fallback） |

**Batch 聚合级别 (`score_batch` → `FactCheckResult.score`)：**

| 条件 | score |
|------|-------|
| `total_claims == 0` | `"N/A"` |
| `red_count > 0` | `"FAIL"` |
| `yellow_count > total_claims * 0.3` | `"WARN"` |
| otherwise | `"PASS"` |

**B 需要做的：**
- 确认以上映射没有未覆盖的边界情况
- 特别确认 `not_found` 的 confidence 为 0 时不会意外触发 red

### B2. 确认 `render_factcheck_markdown` 输出满足 C 的 report 嵌入需求

当前 `render_factcheck_markdown` 已能输出结构化 Markdown。确认：
- 输出包含 🟢🟡🔴 emoji（非纯 HTML color span，以兼容 QQ）
- 输出包含每条 claim 的 detail card（claim_text + verdict + confidence + evidence_snippet）
- 输出适合直接嵌入 C 的 `crossdisc_report.md` 第 1 节
- 与 `render_factcheck_summary` 的 compact 输出不冲突

如果当前 render 输出有任何不满足以上要求的地方，调整。

### B3. 考虑在 verify_claim 返回中支持透传 claim_id

**可选改动，需与 A 协商：**

A 的 `verify_claim` 当前不接受 `claim_id` 参数，返回的 claim_id 恒为空。这要求 Agent 做映射。

方案：在 MCP tool `verify_claim` 的签名中增加可选参数 `claim_id: str = ""`，如果传入则原样透传到返回的 `VerificationResult.claim_id`。

好处：
- Agent 不需要手动 `vr.claim_id = claim.claim_id`
- 减少 Agent 犯错的机会

风险：
- 工具接口与 A 的 Python 函数签名不一致（tool 层面可以加，Python 层面不改）

### B4. 不需要做的

- **不需要重写 scoring 逻辑** — 已有 24 个测试验证，行为正确
- **不需要单独为 PASS/WARN/FAIL 做 per-claim 映射** — `score_batch` 的聚合逻辑是正确的
- **不需要改 `not_found` 为 red** — 未找到引用文献 ≠ 声明错误，yellow 是合理的

## 4.3 B 的验收标准

| 检查项 | 预期结果 |
|---|---|
| `score_verification` 所有 7 条分支有对应测试 | 是（已有 24 tests） |
| `score_batch` 批量评分 edge case 处理正确 | 是 |
| `render_factcheck_markdown` 输出包含 🟢🟡🔴 | 是 |
| `render_factcheck_markdown` 输出包含 PASS/WARN/FAIL | 是 |
| 输出可直接嵌入 C 的 report（纯 Markdown，QQ 兼容） | 是 |
| (可选) `verify_claim` 支持透传 claim_id | 是/否 |

---

# 5. C 同学分工：Memory、Evidence Chain、Report 与 Skill

## 5.1 C 的核心目标

C 负责最终交付质量：
- `crossdisc_idea/SKILL.md` — Agent pipeline 入口（C 已创建，本轮继续迭代）
- memory schema — 确保每次 experiment 有结构化记录
- evidence chain — 确保报告可审计
- report 措辞一致性 — 不强于 FactCheck 结果

## 5.2 C 的具体任务

### C1. 继续迭代 `crossdisc_idea/SKILL.md`（已部分完成）

**本轮已修改：**
- Phase 2：claim_id mapping 强化为 `CRITICAL — MUST DO` + 代码示例
- Phase 3：强制调用 `score_batch` / `render_factcheck_markdown` + 完整 import/call 示例
- Phase 5：要求输出嵌入 `render_factcheck_markdown(batch)` 的输出，含 🟢🟡🔴

**还需与 A 协作验证：**
- 用新 skill 指令跑一个 quest，确认 Agent 服从所有 MUST 要求

### C2. 设计强制 memory schema

当前系统只能证明"有 memory 能力"，但不能证明"每次实验都记录"。

C 需要定义固定 schema，例如：

```json
{
  "run_id": "...",
  "experiment_id": "...",
  "timestamp": "...",
  "paper_id": "...",
  "input_pdf_path": "...",
  "claims": [
    {
      "claim_id": "C-001",
      "claim_text": "...",
      "evidence_refs": ["E-001"],
      "checker_status": "WARN",
      "traffic_light": "🟡"
    }
  ],
  "aggregate_score": "WARN",
  "green_count": 0,
  "yellow_count": 3,
  "red_count": 0,
  "artifacts": ["crossdisc_report.md"]
}
```

建议每次任务结束时 Agent 调用 `mcp__memory__write` 写入该 schema。

### C3. 修复 memory write 报错

当前报错 `Unknown memory kind: episode` 出现了 2 次。

两种修复方案：
```
方案 1：注册 "episode" 为合法 memory kind（需改 artifact server）
方案 2：把 "episode" 改成系统已有的合法 kind（如 "experiment" / "knowledge" / "fact"）
```

短期建议方案 2，查一下当前系统支持哪些 kind，选用最合适的。

### C4. 修改报告结构，加入 Evidence Chain 表格

建议把报告第 2 节改成结构化 evidence chain 表格：

| Claim ID | Claim | Evidence ID | Verification Source | Verdict | Confidence | Traffic Light |
|---|---|---|---|---|---|---|
| C-001 | FL enables... | E-001 | Semantic Scholar (abstract) | uncertain | 0.45 | 🟡 |
| C-002 | MHPFL enables... | E-002 | arXiv (abstract) | not_found | 0.00 | 🟡 |
| C-003 | Data samples... | E-003 | Crossref (abstract) | uncertain | 0.45 | 🟡 |

对应项目核心卖点：
> 工具调用可检查，证据来源可追踪，Agent 协作过程可审计。

同时要求 Agent 调用 `mcp__artifact__record` 把 report 写入 evidence store（当前 014 只用了 interact，没有 record）。

### C5. 降低报告中的强措辞（014 实测问题）

014 的报告中，FactCheck 结果是 WARN / Uncertain，但后文出现了：

```
"perfectly matches"
"genuinely novel"
"strongest"
```

这会削弱报告可信度。

建议使用以下替换规则：

| 原强措辞 | 改为 |
|---|---|
| perfectly matches | partially aligns with |
| genuinely novel | potentially novel |
| strongest evidence | relatively stronger evidence |
| fully supports | provides partial support for |
| clearly demonstrates | suggests / indicates |
| This is a genuinely novel direction | This may indicate a potentially novel direction, but further comparison with related work is needed |
| This perfectly matches the target problem | This partially aligns with the target problem, but the current evidence is not sufficient to claim a perfect match |

要求在 SKILL.md Phase 4 中加入措辞规范，或在 prompt builder 中注入 hedging 要求。

### C6. PDF parser 问题暂不硬修，但记录 fallback

PDF parser 的修复是 A 的任务（A3），C 在 report 层面需要：

1. 如果 `parse_pdf` 失败，在 evidence chain 中记录：
   ```
   parser_status: failed
   extraction_method: bash_fallback
   ```
2. 报告中标注"文本提取可能不完整"
3. 不在 evidence chain 中掩盖提取质量信息

## 5.3 C 的验收标准

| 检查项 | 预期结果 |
|---|---|
| SKILL.md 是否包含 claim_id mapping + score/render 强制要求 | 是（已完成） |
| 是否有强制 experiment memory schema | 是 |
| memory write 是否不再报错 | 是 |
| 第二次实际 run 中 Agent 是否服从 SKILL.md 所有 MUST 要求 | 是 |
| 报告是否有 evidence chain 表格 | 是 |
| Agent 是否调用了 `mcp__artifact__record` | 是 |
| 报告措辞是否和 FactCheck 结果一致（不强于） | 是 |
| parser fallback 是否被记录在 evidence chain | 是 |

---

# 6. 基础设施修复（三人协商）

### I1. 模型兼容性问题（严重，阻塞性）

**问题**：deepseek-v4-pro 不支持 Anthropic Messages API 的 `system` role，Claude CLI 一定发 `system` 消息，导致 ~80% run 直接 API 400 崩溃。014 侥幸跑通了一次。

**影响**：无论 A/B/C 怎么改代码，大部分 run 根本跑不到 factcheck 阶段就挂了。

**选项**：
1. 换成真正支持 Anthropic Messages API 的模型（Claude Sonnet/Opus）
2. 在 runner 层做 message 转换（system → user），但可能破坏 skill 加载
3. 换 runner（codex/opencode），但需要验证它们的 MCP 兼容性

**建议**：短期用选项 1（换模型跑一次完整验证），长期由 A/B 评估选项 2/3。

---

# 7. 三人协作顺序

建议按照以下顺序推进（考虑已有进展）：

```text
第一步（已完成）：C 修改 SKILL.md — claim_id mapping + 强制 score/render
第二步（当前）：A 修复 parse_pdf 不再返回垃圾数据
第三步：A + C 用修复后的 parse_pdf 跑一次新的 quest，验证 Agent 服从指令
第四步：根据 run 结果，B 微调 render 输出格式
第五步：C 加 memory schema、evidence chain、措辞降级
第六步：三人一起跑 end-to-end demo（最好换模型跑）
```

如果第三步发现 Agent 仍然绕过工具，A 需要在 `prompts/builder.py` 中做更强制性的 stage prompt 注入。

---

# 8. 最小可交付版本

如果时间紧，最小版本可以这样定：

| 人员 | 最小任务 |
|---|---|
| A | 修复 `parse_pdf` 垃圾输出；如 Agent 仍绕过工具，加固 prompt |
| B | 确认 `render_factcheck_markdown` 输出可直接嵌入 C 的 report |
| C | 完成 SKILL.md 本轮修改；memory write 报错修复；措辞降级规则写入 Phase 4 |

完成这个最小版本后，系统应该具备：

```text
parse_pdf (不返回垃圾)
→ verify_claim
→ claim_id mapping
→ score_batch
→ render_factcheck_markdown
→ report includes 🟢🟡🔴 + PASS/WARN/FAIL + evidence table
→ memory write 成功
```

---

# 9. 最终验收清单

## 9.1 工具调用验收

| 项目 | 是否通过 |
|---|---|
| `score_verification` 被调用 | ☐ |
| `score_batch` 被调用 | ☐ |
| `render_factcheck_markdown` 被调用 | ☐ |
| `mcp__artifact__record` 被调用 | ☐ |
| Agent 没有绕过 Phase 3 | ☐ |

## 9.2 Claim 合约验收

| 项目 | 是否通过 |
|---|---|
| 原始 `claim_id` 被保留 | ☐ |
| verify 后结果能映射回原 claim | ☐ |
| evidence 能通过 claim_id 对齐 | ☐ |

## 9.3 报告验收

| 项目 | 是否通过 |
|---|---|
| 报告包含 🟢 / 🟡 / 🔴 | ☐ |
| 报告包含 PASS / WARN / FAIL | ☐ |
| 报告包含 per-claim detail card | ☐ |
| 报告包含 evidence chain 表格 | ☐ |
| 报告措辞和 FactCheck 结果一致（不强于） | ☐ |

## 9.4 Memory 验收

| 项目 | 是否通过 |
|---|---|
| 每次实验有 `run_id` | ☐ |
| 每次实验记录输入 prompt | ☐ |
| 每次实验记录输出结果 | ☐ |
| 每次实验记录 evidence refs | ☐ |
| 每次实验记录 checker score | ☐ |
| memory write 不再报错 | ☐ |

## 9.5 Parser/Fallback 验收

| 项目 | 是否通过 |
|---|---|
| PDF parser 不再返回 > 50KB 垃圾数据 | ☐ |
| parser 异常时返回明确 error（非垃圾） | ☐ |
| fallback extraction 被记录在 evidence chain | ☐ |

## 9.6 基础设施验收

| 项目 | 是否通过 |
|---|---|
| Run 成功率 > 50%（非 model 兼容性导致崩溃） | ☐ |

---

# 10. 一句话总结

本轮修改的重点不是继续堆功能，而是把现有功能串成一个真正可审计的闭环：

> Agent 必须调用工具，工具必须给出结构化评分，报告必须保留证据链，memory 必须记录每次实验。
