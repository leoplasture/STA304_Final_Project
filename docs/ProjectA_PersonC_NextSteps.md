# Person C 接手说明

## 当前状态

FactCheck pipeline 端到端已全部跑通（quest 021 验证）。A 和 B 的代码改动已完成并推到 `origin/dev`（`71bdff3`）。

### 021 运行结果

```
parse_pdf → 40 claims (35/40 引用标题已成功解析)
→ verify_claim ×40 (不再跳过空 title，fallback 搜索生效)
→ score_batch (FAIL: 🟢7 🟡29 🔴4)
→ render_report (含 RYG emoji 表格)
→ render_summary
→ Write + artifact.interact → QQ 发送
```

- `bash_exec` 手动 fallback: **0 次**
- 错误: **0**
- 报告: 166 行，含 5 个跨学科 bridge、evidence table

---

## C 需要做的事（按优先级）

### C1. 修复 memory write 报错（高优）

**报错信息**：`Error executing tool write: Unknown memory kind: episode`

**位置**：Quest 运行中 Agent 调用 `mcp__memory__write` 时，传入 `kind: "episode"` 但系统不支持。

**排查方向**：
- 查看 `mcp__memory__write` 工具支持的 `kind` 枚举值
- 合法值大概率在 `deepscientist/mcp/server.py` 的 memory namespace 定义中，或在 `deepscientist/memory/` 模块
- 短期修复：把 SKILL.md 或 prompt builder 里的 `kind: "episode"` 改成合法值（如 `"experiment"` / `"knowledge"`）
- 长期修复：注册 `episode` 为合法 memory kind

### C2. 设计实验 memory schema（高优）

每次 quest 结束后，Agent 应写入结构化 memory。建议 schema：

```json
{
  "run_id": "...",
  "quest_id": "...",
  "timestamp": "...",
  "paper_title": "...",
  "claims_parsed": 40,
  "claims_with_title": 35,
  "verification_results": {
    "green": 7, "yellow": 29, "red": 4,
    "score": "FAIL"
  },
  "artifacts": ["crossdisc-idea-report.md"],
  "cross_discipline_bridges": [...],
  "verifier_notes": "..."
}
```

对应位置：SKILL.md Phase 5 或 `prompts/builder.py` 的 crossdisc_idea 合同段。

### C3. Evidence chain 表格标准化（中优）

021 报告已有雏形（`Evidence Table` 节），但格式未标准化。建议固定模板：

```markdown
| Evidence ID | Claim ID | Source | Extraction Method | Verdict | Traffic Light |
|-------------|----------|--------|-------------------|---------|---------------|
| E-001 | C001 | Semantic Scholar | parse_pdf | supported | 🟢 |
| E-002 | C002 | Semantic Scholar | parse_pdf | not_found | 🟡 |
| (parser failed claims) | C00X | — | bash_fallback | — | ⚪ |
```

要求：
- 每条 claim 对应一个 evidence ID
- 标注 extraction method（`parse_pdf` / `bash_fallback`）
- 与 A 的 `evidence_chain.py`（`E00X` 编号）对齐

### C4. 报告措辞降级（中优）

021 报告整体自省程度好（自标了 4 个 🔴 可能是误报），但仍有可改进处。建议在 SKILL.md Phase 4 加入措辞规则：

| 原词 | 改为 |
|------|------|
| perfectly matches | partially aligns with |
| genuinely novel | potentially novel |
| fully supports | provides partial support for |
| clearly demonstrates | suggests / indicates |

已在修改计划 `docs/FactCheck_Agent_ABC_Modification_Plan.md` Section 5-C4 中有详细对照表。

### C5. SKILL.md 审阅（低优）

本轮我们对 `crossdisc_idea/SKILL.md` 做了较大改动：
- Phase 2: claim_id 透传 + 禁止跳过空 title
- Phase 3: 改为 MCP tool 调用 + 强制评分
- Phase 5: 要求嵌入 `render_report` 输出

C 应该审阅一遍，确认措辞和流程和 C 的设计意图一致。

### C6. verify_claim 误报问题（低优，与 A 协作）

021 中 4 个 🔴 是 verifier 论文匹配错误（把 C008 "FjORD" 匹配到了错误的 FjORD 论文）。需要在报告层面标注，以及在 `semantic_verifier.py` 中改进搜索精度。短期建议报告里加一段 "Known Verifier Limitations"。

---

## 关键文件位置

| 文件 | 说明 |
|------|------|
| `src/skills/crossdisc_idea/SKILL.md` | C 的 skill 文件，本轮已改，需审阅 |
| `src/deepscientist/prompts/builder.py:278` | A 加的强制合同注入点 |
| `src/deepscientist/mcp/server.py:2644-2800` | factcheck MCP tools（含 B 的 wrapper） |
| `src/deepscientist/factcheck/claim_extractor.py` | A 的 parser（本轮修了参考文献解析） |
| `src/deepscientist/factcheck/semantic_verifier.py` | A 的 verifier（本轮加了 fallback 搜索） |
| `docs/FactCheck_Agent_ABC_Modification_Plan.md` | 三人修改计划，C 的任务在 Section 5 |

## 如何测试

```bash
# 重启 daemon
ds --restart

# 通过 QQ 发 PDF + /crossdisc_idea 指令即可触发全流程
# 或直接看 quest 日志：
ls DeepScientist/quests/<quest_id>/.ds/runs/<run_id>/
```

## 快速验证清单

- [ ] 开新 quest，上传 PDF，发 `/crossdisc_idea`
- [ ] parse_pdf 返回 claims 且大部分有 `cited_paper_title`
- [ ] verify_claim ×N 被调用
- [ ] score_batch 被调用
- [ ] render_report 输出含 🟢🟡🔴
- [ ] 报告中 FactCheck 分数和红绿灯与 render_report 一致
- [ ] `mcp__memory__write` 不再报 `Unknown memory kind: episode`
- [ ] `mcp__artifact__record` 被调用
- [ ] 报告措辞不强于 FactCheck 结果
