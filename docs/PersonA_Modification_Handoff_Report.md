# PersonA 修改交接报告

## 1. 任务背景与问题清单

本轮修改针对 FactCheck Agent 在 `crossdisc_idea` 流程中的关键问题，重点是：

1. Phase 3 常被绕过，Agent 手写评分和表格，未调用 B 的工具链。
2. `claim_id` 映射依赖 Agent 手动补齐，存在遗漏风险。
3. `parse_pdf` 对 PDF 文本提取质量差，可能返回超大垃圾内容。
4. 解析失败时缺少标准化 fallback 错误结构。
5. 缺少可执行的 A 验收测试，无法稳定证明“问题已修复”。

---

## 2. 修改范围

### 2.1 Parser 修复（A3）

- 文件：`src/deepscientist/factcheck/claim_extractor.py`

主要改动：
- 增加提取清洗逻辑：控制字符清理、常见 PDF 操作符噪声清理。
- 增加可读性判定：当可读比例低于阈值时抛出 `PDFExtractionError`。
- 增加提取长度保护：`MAX_EXTRACTED_CHARS = 200_000`。
- 增加 claim 截断：`MAX_RETURNED_CLAIMS = 40`。
- 解析失败统一抛 `PDFExtractionError("PDF text extraction failed")`，避免返回天量垃圾。

效果：
- 不再把不可读 PDF 流直接暴露给上游 Agent。
- 输出规模和返回结构可控，降低 token 淹没风险。

### 2.2 MCP 工具层 fallback 与 claim_id 透传（A2 可选项 + A3 fallback）

- 文件：`src/deepscientist/mcp/server.py`

主要改动：
- `parse_pdf` 工具捕获 `PDFExtractionError` 并返回：
  - `{"ok": false, "error": "PDF text extraction failed", "fallback_recommended": true}`
- `verify_claim` 工具签名新增 `claim_id: str = ""`，若调用方传入则原样透传到返回结果。

效果：
- 解析失败时上游有明确、标准化 fallback 信号。
- `claim_id` 可由工具层直接保留，减少 Agent 忘记映射的概率。

### 2.3 Prompt Builder 强制执行合同（A1 fallback）

- 文件：`src/deepscientist/prompts/builder.py`

主要改动：
- 当 `skill_id == "crossdisc_idea"` 时注入 `FactCheck Execution Contract`，强制要求：
  - 必须进行 `claim_id` 映射。
  - 必须调用 `score_batch`，禁止手工 PASS/WARN/FAIL。
  - 必须调用 `render_factcheck_markdown`，禁止手写 FactCheck 表格。
  - 必须调用 `mcp__artifact__record` 写入 evidence store。
  - `parse_pdf` fallback 时必须走替代提取并在报告中保留 parser 失败信息。

效果：
- 将“技能建议”升级为“运行时硬约束”，降低 Phase 3 被绕过风险。

### 2.4 测试与验收补强（A4）

新增/更新文件：
- `tests/test_factcheck.py`
- `tests/test_mcp_servers.py`
- `tests/test_prompt_builder.py`
- `tests/test_persona_a_acceptance.py`（新增）

关键测试覆盖：
- parser 截断行为、不可读 PDF 失败路径。
- MCP `verify_claim` 的 `claim_id` 透传。
- MCP `parse_pdf` fallback 错误结构。
- `crossdisc_idea` prompt 注入强制合同。
- PersonA 验收级测试：覆盖 `score_batch`、`render_factcheck_markdown`、`claim_id` 保留、报告 RYG/PASS-WARN-FAIL、`artifact.record`、uncertain/not_found 可继续产出、fallback 返回体小于 50KB。

---

## 3. 验证结果

已执行并通过的关键测试：

- `tests/test_factcheck.py`：通过
- `tests/test_factcheck_integration.py`：通过
- `tests/test_mcp_servers.py`（新增 factcheck 两项）：通过
- `tests/test_prompt_builder.py`（新增 crossdisc 合同用例）：通过
- `tests/test_persona_a_acceptance.py`：`2 passed`

对应 A 验收标准结论：
- `score_batch` 调用：已验证
- `render_factcheck_markdown` 调用：已验证
- `claim_id` 保留：已验证
- 报告含 🟢🟡🔴：已验证
- 报告含 PASS/WARN/FAIL：已验证
- Phase 3 绕过风险：已通过 prompt 强制合同约束并有验收测试覆盖
- `parse_pdf` 垃圾输出控制：已通过截断+fallback 机制验证
- `parse_pdf` 明确 error：已验证
- `artifact record` 调用：已验证
- uncertain/not_found 仍可产出报告：已验证

---

## 4. 备注

- 本次提交中未纳入 `uv.lock` 的环境噪声变更。
- 若后续要进一步做真实 runner/QQ 端到端验收，可在 quest 运行日志中增加工具调用审计统计（调用次数、阶段覆盖、失败重试轨迹）。
