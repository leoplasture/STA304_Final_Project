# Project A 完成度分析与后续行动指南

## 当前状态总览

| # | Project 要求 | 状态 | 证据 |
|---|---|---|---|
| 1 | QQ/WeChat 接收科研任务 | ✅ | QQ bot 正常收发，evidence_store 记录完整 |
| 2 | 处理至少一种输入材料 | ✅ | 文本 + 图片 + PDF（3 种） |
| 3 | 报告含 evidence id + 证据表 | ✅ | `final_report.md` 含 [E012][E012-img][E018-pdf] + Evidence Table |
| 4 | 区分三类内容 | ✅ | [E00X] + [推断] + [待验证] + 裸断言检测 |
| 5 | 5+1 测试案例 | ✅ | 68 tests，含 fake ID、空 store、边界案例 |
| 6 | 扩展前后对比 | ⚠️ | 有 `evidence_integration_report.md`，需补充实测数据 |
| 7 | 红黄绿评分（老师最新要求） | ✅ | `traffic_light.py` 完整实现 🟢🟡🔴 |
| 8 | QQ 真实交互展示 | ⚠️ | 代码完成，但 Runner crash 阻塞端到端演示 |
| 9 | 独立工具调用（≥B-） | ✅ | factcheck MCP 工具 + evidence chain + audit |

---

## 还需要完成的 3 件事

### 第 1 件：更新 evidence_integration_report.md 加入实测数据

**当前状态**：报告只有理论对比，没有今天的实际运行数据。

**需要补充**：
- final_report.md 的审计结果截图/摘录
- 四类标注的实际计数（supported=5, inferred=2, unverified=2, bare=8）
- FactCheck pipeline 跑通的数据（40 claims → 🟢🟡）
- PDF 证据录制数据（E018-pdf: 14页, SHA256, 80KB text sidecar）

**文件**：`docs/evidence_integration_report.md`

---

### 第 2 件：完成 QQ bot 端到端演示

**阻塞原因**：Runner (Claude CLI) 反复 crash。不是代码问题——是环境问题（C: 盘仅 600MB + Windows 兼容性）。

**解决方案（按推荐程度排序）**：

A. **换一台机器跑**（推荐）：在 C: 盘有足够空间（>5GB）的 Windows 上，或 Linux/Mac 上运行
B. **清理 C: 盘**：释放 5GB+ 空间后重试
C. **用本地模型**：装 Ollama + qwen2.5，绕过 DeepSeek API 兼容问题

**验证步骤**（在干净环境上）：
```
1. ds --restart
2. QQ bot 发送 PDF + "/crossdisc_idea"
3. 等待 2-5 分钟
4. Bot 返回 RYG 报告
```

---

### 第 3 件：跑完整测试套件 + 截图留存

```powershell
# 全部 68 个测试
D:\Python312\Scripts\pytest.exe tests/test_connector_evidence.py tests/test_evidence_chain.py tests/test_evidence_audit.py tests/test_factcheck.py tests/test_traffic_light.py tests/test_factcheck_integration.py -v

# 如果只想跑 Role C 相关的
D:\Python312\Scripts\pytest.exe tests/test_connector_evidence.py tests/test_factcheck_integration.py -v
```

截取 **68 passed** 的结果作为证据。

---

## 评分对标

| 评分标准 | 我们达到的水平 | 证据 |
|---------|--------------|------|
| C+: 仅靠 prompt | **远超** | 有独立 MCP 工具（factcheck namespace）+ evidence chain + audit |
| B-: 独立工具+调用 | **达到** | parse_pdf / verify_claim / traffic_light / record_connector_event 均为自己实现 |
| B/B+ 加分项 | **可能** | PDF 多模态支持 + RYG 渲染 + crossdisc_idea skill + 集成测试 |

---

## 提交前检查清单

- [ ] 68 tests 全部通过（截图）
- [ ] final_report.md 四类标注完整
- [ ] evidence_integration_report.md 更新实测数据
- [ ] QQ bot 端到端演示（或说明 Runner 环境问题）
- [ ] Git 全部提交推送
- [ ] 三人 handoff draft 齐全（A/B/C）
