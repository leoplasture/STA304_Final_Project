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

本方向要求为科研 Agent 增加"证据链追踪模块"，使系统输出可追踪、可检查、可复现。具体包括：
- 记录输入材料与工具输出来源
- 为关键结论标注 evidence ID 并说明来源位置
- 区分三类内容：明确支持 / 合理推断 / 证据不足
- 在 QQ 真实交互中展示该功能
- 至少 5 个测试案例，含 1 个边界案例

我们在此基础上进一步扩展——不仅追踪证据，还增加了**文献引用的语义验证**（Semantic Scholar / arXiv / Crossref API）和**红黄绿三色评分**机制。

---

## 2. 选择的基础系统

**DeepScientist**（https://github.com/ResearAI/DeepScientist）——一个本地优先的自主科研工作室系统，管理长期研究 workflow。

**选用理由**：
- 现有 QQ connector 支持真实多模态消息交互
- MCP server framework 支持自定义工具注册
- Quest workflow engine 支持 skill 编排
- Claude CLI runner 提供 LLM 调用基础设施
- 开源 MIT 协议，允许二次开发

**我们的改造范围**：新建 4 个 Python 模块（claim_extractor, semantic_verifier, traffic_light, factcheck_render）+ 1 个 Skill 文件（crossdisc_idea）+ 修改 3 个框架文件（server.py, builder.py, mcp/server.py）。其余为框架原有组件。

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
│ 上传 PDF  │    │ Skill (C)     │    │ (A: PyPDF2)  │    │ ×N (A: S2/    │
└──────────┘    └───────────────┘    └──────────────┘    │ arXiv/Crossref)│
      ↑                                                   └───────┬───────┘
      │                                                           ↓
      │              ┌───────────────────┐    ┌───────────────────────┐
      │              │ render_report (B) │ ←  │ score_batch (B)       │
      │              │ 彩色 Markdown 表格  │    │ 🟢🟡🔴 traffic_light  │
      │              └─────────┬─────────┘    └───────────────────────┘
      │                        ↓
      │              ┌───────────────────────┐
      │   QQ 返回     │ artifact__record +   │
      └──────────────│ memory__write (C)    │
                     └───────────────────────┘
```

### 4.2 三层验证链路

| 层级 | 组件 | 功能 | 负责人 |
|------|------|------|--------|
| 入口层 | QQ connector + evidence chain | 多模态消息录制，生成 E00X 证据 ID | C |
| 工具层 | claim_extractor + semantic_verifier | PDF 解析 + Semantic Scholar/arXiv/Crossref 三源验证 | A |
| 评分层 | traffic_light + factcheck_render | 🟢🟡🔴 七条评分分支 + Markdown 渲染 | B |
| 编排层 | crossdisc_idea SKILL.md | 5-Phase 状态机（Score→Render→Record→Memory→Deliver） | C |
| 强约层 | prompts/builder.py HARD STOP RULE | 所有强制工具调用不允许跳过 | A |

### 4.3 证据链数据结构

所有证据以 `E{NNN}` 格式存入 `evidence_store.json`：

| 证据类型 | ID 格式 | 内容 | 示例 |
|---------|---------|------|------|
| QQ 文本消息 | E001 | 消息文本 + 发送者 + 时间戳 + SHA256 | "请分析这篇论文" |
| QQ 图片附件 | E001-img | 文件名 + 尺寸 + 格式 + SHA256 | 800×600 PNG |
| QQ PDF 附件 | E001-pdf | 文件名 + 页数 + SHA256 + 文本 sidecar | 14 pages, 80KB text |

`audit_report()` 自动扫描报告中的 `[E001]`、`[E001-img]`、`[E001-pdf]` 引用，交叉验证 evidence_store。

### 4.4 强制合同机制

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
| test_factcheck.py | 4 | A |
| test_traffic_light.py | 23 | B |
| test_factcheck_integration.py | 10 | C |
| test_prompt_builder.py | 1 | A |
| **总计** | **68** | **全部通过** |

### 5.2 真实 Quest 验证（6 个学科）

| Quest | 学科领域 | 论文主题 | Claims | verify_claim | 评分 | 工具合规 |
|-------|---------|---------|--------|-------------|------|---------|
| 027 | ML/联邦学习 | pFedAFM | 40 | 40 | 🟢17 🟡18 🔴5 FAIL | 6/6 ✅ |
| 028 | 医学教育 | Subinternship Directors | 8 | 8 | 🟢1 🟡6 🔴1 FAIL | 6/6 ✅ |
| 029 | 计算化学 | DFT Metal Clusters | 1 | 1 | 🟢1 🟡0 🔴0 PASS | 6/6 ✅ |
| 030 | 优化理论 | SGD Convergence | 40 | 49 | 🟢10 🟡28 🔴2 FAIL | 6/6 ✅ |
| 031 | 引力波物理 | LIGO PEMcheck | 40 | 45 | 🟢2 🟡37 🔴1 FAIL | 6/6 ✅ |
| 032 | ML 综述 | Federated Learning Survey | N/A | 1 | — | 6/6 ✅ |

**总计**：996 个 events，144 次 verify_claim 调用，36/36 强制工具调用全部完成。

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

### 6.4 API 兼容性导致 Runner 崩溃（早期版本）

**案例**：开发早期（v2.1 阶段），DeepSeek API 不支持 Anthropic Messages API 的 `system` role，导致 ~80% 的 quest 在启动阶段崩溃。

**修复**：锁定 Claude Code 版本到 2.1.153，添加 `--strict-mcp-config`，过滤 PATH 中的系统 Python，将 TEMP 重定向到非系统盘。

### 6.5 Agent 绕过工具链（中期版本）

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
| DeepSeek API 兼容性 | Claude Code 版本升级可能再次引入问题 | 中 |
| 视频/音频不支持 | 仅处理文本、图片、PDF | 低 |

### 7.2 未来改进

1. **Full-text 验证**：集成 arXiv open-access 全文检索，降低 uncertain 比例
2. **本地模型 fallback**：集成 Ollama + sentence-transformers，减少对外部 API 依赖
3. **Claim 质量改进**：将 `claim_extractor` 的 LLM 抽取替换为结构化 NLP pipeline
4. **多 Connector 支持**：将事实核查能力扩展到 WeChat、Discord 等 connector
5. **缓存与限速**：为 verify_claim 增加结果缓存层，避免重复 API 调用

---

## 8. 个人与小组贡献说明

### 8.1 小组贡献概览

| 成员 | 角色 | 核心技术贡献 |
|------|------|-------------|
| 廖苗懿 | Person A (工具层) | claim_extractor.py（PyPDF2 + 参考文献解析）、semantic_verifier.py（S2/arXiv/Crossref 三源验证）、prompts/builder.py HARD STOP RULE |
| 熊筱瑜 | Person B (评分渲染) | traffic_light.py（7 分支 RYG 评分）、factcheck_render.py（彩色 Markdown 渲染）、MCP server.py 5 个工具注册 |
| 刘宇翔 | Person C (入口+集成) | crossdisc_idea/SKILL.md（5-State Machine）、QQ 多模态证据录制、evidence chain 表格、memory schema、措辞规范、集成测试 |

### 8.2 个人贡献详述（Person C — 刘宇翔）

**新建文件**：
- `src/skills/crossdisc_idea/SKILL.md` — 跨学科 idea skill（5-phase pipeline + 状态机 + exit checks）
- `tests/test_factcheck_integration.py` — 10 个端到端集成测试
- `tests/test_connector_evidence.py` — 6 个 QQ connector 证据录制测试
- `docs/ProjectA_IntegrationReport.md` — 全流程集成报告
- `docs/ProjectA_PersonC_Handoff_Draft.md` — 团队交接文档
- `docs/Final_Project_Report.md` — 本报告

**修改文件**：
- `src/deepscientist/evidence_chain.py` — PDF 附件支持（E00X-pdf）、文本占位符修复编号断层
- `src/deepscientist/evidence_audit.py` — 扩展正则支持 E\d+-pdf 格式
- `src/deepscientist/prompts/builder.py` — 图片/PDF 路径可见性 + attachment 处理规则
- `src/deepscientist/runners/claude.py` — MCP PATH 过滤、TEMP 重定向、strict-mcp-config
- `src/deepscientist/runners/simple_cli.py` — stdin 写入时序修复
- `src/deepscientist/mcp/server.py` — interact 异步 dispatch 超时保护
- `src/deepscientist/artifact/service.py` — channel.send() 线程超时

**Runner 环境修复**（开发期间，非框架修改）：
- Claude CLI 版本锁定（2.1.152/2.1.153）
- 系统 Python 进程隔离（PATH 过滤）
- C: 盘磁盘满导致的各种 PermissionError/死锁修复
- QQ connector 重复投递修复

**测试与验证**：
- 编写 16 个测试用例（C 角色），全部通过
- 参与 6 个真实 quest 的端到端验证
- 证据链表格标准化、措辞降级规则制定
