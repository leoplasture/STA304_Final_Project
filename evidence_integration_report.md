# DeepScientist 证据链集成前后对比分析报告

## 1. 概述

本报告对比分析 DeepScientist 科研 agent 在集成证据链（Evidence Chain）模块前后的系统行为变化，重点关注 QQ 连接器消息处理的可追溯性和审计能力。证据链系统由三个角色协作完成：Role A 负责证据链核心存储与 runners 埋点，Role B 负责 Prompt 规则注入与离线审计脚本，Role C 负责 QQ 多模态证据识别与集成测试。

## 2. 集成前：原始 QQ 消息处理

### 2.1 消息流转

集成前，QQ 用户的文本和图片消息经过以下路径进入系统：

```
QQ用户 → QQ Gateway (WebSocket) → handle_connector_inbound()
  → QQRelayChannel.ingest() → normalize_inbound()
  → _route_connector_message()
  → _materialize_connector_attachments() → 下载图片到本地 userfiles/
  → submit_user_message() → LLM 处理
```

### 2.2 存在的问题

| 问题 | 影响 |
|------|------|
| **无结构化消息记录** | 用户文本消息直接进入 LLM 对话上下文，仅在 inbox.jsonl 中保存原始记录，无法按 quest 维度检索 |
| **图片附件无元数据索引** | 图片下载到 `userfiles/qq/` 后仅作为文件路径传递给 LLM，无结构化元数据（尺寸、哈希、格式）记录 |
| **无法追溯结论来源** | 无法回答"报告中某个结论是由用户的哪条消息/哪个图片触发的" |
| **引用标注全靠 LLM 自觉** | 研究报告中引用来源时无机器可验证的 ID 体系，无法自动检测虚构引用 |
| **缺乏证据完整性检查** | 无法自动判断"被引证据是否存在"、"有哪些证据从未被引用" |

## 3. 集成后：全链路证据追踪

### 3.1 新增模块

| 模块 | 职责 | 负责人 |
|------|------|--------|
| `evidence_chain.py` | 证据 ID 生成、存储、查询（record_event / query_events / get_evidence_by_id / export_store / validate_store） | A |
| `evidence_audit.py` | 离线审计：交叉验证报告引用 vs evidence_store，三级标注统计，裸断言检测 | B |
| `record_connector_event()` | QQ 消息（文本+图片）证据记录，生成 E00X / E00X-img 格式 ID | C |
| Skills/Prompts 注入 | Agent 报告写作时强制引用证据 ID，三层次标注规则 | B |

### 3.2 数据流变化（新增 C 角色 hook 点）

```
QQ用户 → QQ Gateway → handle_connector_inbound()
  → QQRelayChannel.ingest()
  → _route_connector_message()
    → _materialize_connector_attachments() → 下载图片
    → ★ record_connector_event() ★      ← C 角色新增
      ├─ 文本 → E001 (connector_text)
      └─ 图片 → E001-img (connector_image, SHA256+尺寸+格式)
    → submit_user_message() → LLM 处理
```

### 3.3 证据条目格式

每条 QQ 消息产生 1~N 条证据条目，存入 `.ds/evidence/evidence_store.json`：

**connector_text 条目示例：**
```json
{
  "evidence_id": "E001",
  "source_type": "connector_text",
  "tool_name": "connector.qq",
  "args": {
    "text": "请帮我复现这篇论文的 Table 1",
    "sender_id": "user_001",
    "sender_name": "张三",
    "conversation_id": "qq:direct:user_001",
    "message_id": "msg_abc123"
  },
  "status": "ok",
  "payload_sha256": "a1b2c3..."
}
```

**connector_image 条目示例：**
```json
{
  "evidence_id": "E001-img",
  "source_type": "connector_image",
  "tool_name": "connector.qq.image",
  "args": {
    "filename": "test_chart.png",
    "content_type": "image/png",
    "width": 800,
    "height": 600,
    "format": "PNG",
    "sha256": "d4e5f6...",
    "size_bytes": 12345,
    "sender_id": "user_001"
  },
  "source_ref": {
    "kind": "connector_image",
    "path": "userfiles/qq/batch01/test_chart.png",
    "url": "https://qq.example.com/attachments/img_001"
  },
  "output_preview": "image: test_chart.png | 800x600 | PNG | 12.1KB",
  "status": "ok"
}
```

## 4. 维度对比

| 维度 | 集成前 | 集成后 |
|------|--------|--------|
| **消息记录** | 仅 QQ 层面的 inbox.jsonl（未结构化） | evidence_store.json（quest 维度，结构化 16 字段） |
| **图片证据** | 文件下载到 userfiles/，无元数据索引 | 文件 + 元数据(width/height/format/SHA256) + 可引用 ID |
| **证据 ID 体系** | 无 | `E001`(文本) / `E001-img`(图片) 全局唯一，跨模块可引用 |
| **交叉引用验证** | 人工或 LLM 猜测 | `audit_report()` 自动扫描 — 检测 fake ID、未使用证据 |
| **报告可信度量化** | 无法量化 | 三层次标注：[E00X](已验证) / [推断](逻辑推导) / [待验证](需额外实验) |
| **伪造检测** | 无法发现 | 审计模块自动识别引用不存在的 ID（fake_ids） |
| **裸断言检测** | 无 | 自动检测报告中未标注来源的断言句 |
| **图片内容验证** | 无法验证图片是否被篡改 | SHA256 哈希可验证图片完整性 |
| **多轮对话追溯** | 消息序号无意义 | E001→E002→E003 连续编号，可精确追溯指令链 |

## 5. 具体对比案例

### 案例 A：用户通过 QQ 发送实验截图

**集成前流程：**
1. 用户发送图片 `result.png` → QQ Gateway 接收
2. 系统下载到 `quests/quest_001/userfiles/qq/batch_01/result.png`
3. LLM 在对话上下文中看到文件路径
4. LLM 可能在报告中提到"如图所示"，但无法验证

**集成后流程：**
1. 用户发送图片 → 系统下载 + 提取元数据(800×600, PNG, SHA256:abc123)
2. 注册为 `E001-img`，写入 evidence_store.json
3. LLM 在报告中使用 `[E001-img]` 标注
4. `audit_report()` 扫描报告，验证 `[E001-img]` 真实存在
5. 审计结果：`| Supported claims [E...] | 1 |`

### 案例 B：用户发送多轮指令链

用户依次发送：①"开始实验" → ②"运行 baseline" → ③"对比结果"

**集成前：** 三条消息无结构化关联，Agent 行为依据无法回溯到具体指令。

**集成后：** 三条消息分别产生 E001、E002、E003，每条记录的 `args` 中包含完整消息内容和发送者信息。报告中可精确引用 `[E001]`-`[E003]`，审计模块交叉验证。

## 6. 审计能力详解

### 6.1 三类标注统计

审计模块会自动统计报告中的：
- **[E00X]** 引用数（有证据支持的断言）
- **[推断] / [Inferred]** 数（逻辑推导，非直接证据）
- **[待验证] / [Needs Verification]** 数（需要额外验证的断言）
- **裸断言数**（完全未标注来源的句子）

### 6.2 使用方式

```python
from deepscientist.evidence_audit import audit_report, render_audit_markdown

# Agent 通过 QQ 输出报告后
report = open("report_output.md").read()

# 离线审计
result = audit_report(report, "path/to/quest_root")
print(render_audit_markdown(result, "path/to/quest_root"))

# 典型输出：
# | Evidence IDs cited | 5 |
# | Supported claims [E...] | 3 |
# | Inferred claims [推断] | 1 |
# | Unverified claims [待验证] | 1 |
# | Bare claims (no annotation) | 1 |
# | Verdict | PASS |
```

## 7. 测试覆盖

| 测试文件 | 用例数 | 覆盖范围 |
|----------|--------|----------|
| `test_evidence_chain.py` | 10 | call/result 入库、sidecar 识别、event 去重、容错、大输出、过滤查询、按 ID 反查、坏数据校验 |
| `test_evidence_audit.py` | 14 | 正常引用、空 store、fake ID、裸断言、unused evidence、store 损坏、E00X 格式、中英文标注、Markdown 渲染 |
| `test_connector_evidence.py` | 5 | 文本消息、图片消息、混合消息、序号递增、伪造 ID 检测、端到端审计 |
| **总计** | **29** | **全部通过** |

## 8. 局限性与后续工作

- **非图片附件**：PDF、代码文件等附件类型暂未纳入证据记录，可基于相同的 `record_connector_event` 扩展
- **并发写入**：当前 QQ 消息串行处理，证据 store 无并发竞争。若未来引入并行 runner，需添加文件锁
- **图片缩略图**：当前仅记录图片元数据摘要，未生成缩略图文件（完整功能需 Pillow `thumbnail`）
- **视频/音频**：本次实现聚焦图片（`content_type: image/*`），多媒体类型可后续扩展

## 9. 结论

证据链系统将 DeepScientist 的消息处理从"黑箱对话"转变为"可审计的科学研究工作流"。每条 QQ 消息——无论是文本指令还是实验图表——现在都有唯一的、可机器验证的证据 ID。研究报告中的每个事实性断言都可以追溯到具体的证据来源，伪造引用可被自动检测。29 个测试用例全部通过，验证了 A/B/C 三个模块的兼容性和端到端流程正确性。这不仅提升了系统的可信度，也为科学同行评审提供了基础设施。
