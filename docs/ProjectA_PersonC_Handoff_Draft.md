# Project A Person C Handoff Draft

## Scope (Person C Delivered)

Created files:

- `src/skills/crossdisc_idea/SKILL.md` — cross-discipline idea skill with integrated FactCheck pipeline
- `tests/test_factcheck_integration.py` — 10 end-to-end integration tests
- `docs/ProjectA_IntegrationReport.md` — full integration report

Previously delivered (Role C from evidence-chain phase):

- `tests/test_connector_evidence.py` — 6 tests for QQ connector evidence recording
- `docs/evidence_integration_report.md` — evidence chain before/after comparison report

Modified files (Runner + Prompt fixes):

- `src/deepscientist/runners/claude.py` — MCP PATH filtering, TEMP redirection, strict-mcp-config, pythonw→python correction
- `src/deepscientist/runners/codex.py` — same PATH/TEMP fix
- `src/deepscientist/runners/kimi.py` — same PATH/TEMP fix
- `src/deepscientist/runners/opencode.py` — same PATH/TEMP fix
- `src/deepscientist/runners/simple_cli.py` — stdin write timing fix for Claude CLI 2.1.152
- `src/deepscientist/mcp/server.py` — interact tool timeout protection (45s async dispatch)
- `src/deepscientist/artifact/service.py` — channel.send() timeout protection (15s thread)
- `src/deepscientist/skills/installer.py` — redirect claude_root to DS_HOME (fix disk-full C: drive crash)
- `src/deepscientist/prompts/builder.py` — unhide image/PDF attachment paths, add PDF handling rules
- `src/deepscientist/evidence_chain.py` — always emit connector_text entry, add PDF support with text extraction
- `src/deepscientist/evidence_audit.py` — extend regex to recognise E00X-pdf format
- `.gitignore` — exclude DeepScientist runtime artifacts

---

## Interface Contract for A/B

### What C depends on from A/B

C's `crossdisc_idea/SKILL.md` orchestrates A's tools and B's scoring:

| Dependency | From | Status |
|-----------|------|--------|
| `mcp__factcheck__parse_pdf` | A (`claim_extractor.py`) | ✅ Available |
| `mcp__factcheck__verify_claim` | A (`semantic_verifier.py`) | ✅ Available |
| `score_verification` / `score_batch` | B (`traffic_light.py`) | ✅ Available |
| `render_factcheck_markdown` | B (`factcheck_render.py`) | ✅ Available |
| `factcheck` namespace in MCP | B (`server.py`) | ✅ Registered |

### What A/B should know about C's integration

1. **Skill stage position**: `crossdisc_idea` at `skill_order: 55`, between `scout` (50) and `idea` (60). The `factcheck` MCP namespace is already in `prompts/builder.py` line 196.

2. **Claim ID mapping contract**: `verify_claim` returns empty `claim_id`. C's skill instructs the model to copy `claim.claim_id` into `VerificationResult.claim_id` before scoring. C's `test_claim_id_must_be_mapped_externally` validates this contract.

3. **Attachment path visibility**: C's prompt builder change unhides `raw_binary_path` for images and PDFs. The `crossdisc_idea` skill reads the PDF path from the current turn's attachment block.

4. **Evidence recording**: C's `evidence_chain.py` changes ensure connector messages always produce dense E00X numbering and PDFs are recorded with page count + SHA256 + optional text sidecar.

---

## Known Limitations (Important for A/B)

1. **interact tool intermittent timeout**: Despite C's 45s async dispatch fallback in the MCP server, QQ connector gateway latency can still cause timeouts. The system auto-recovers through retry, but delivery latency varies.

2. **System Python MCP duplication**: Under certain daemon configurations, a second set of MCP processes spawns from system Python. This is non-blocking (venv MCP servers still work) but inflates process count. Root cause is in Claude CLI MCP discovery, not in C's code.

3. **DeepSeek model cost**: The system defaults to `deepseek-v4-pro[1m]` (inherited from Claude Code config). C's evidence store cleanup (471 → 37 entries) and retry reduction (4 → 2) mitigate token costs but do not eliminate them. Switching models is constrained by API compatibility (deepseek-chat fails with thinking mode).

4. **PDF parsing quality**: A's current PDF parser is fallback-grade for .pdf files. `.txt/.md` inputs are more reliable for testing. C's `crossdisc_idea` skill documents this limitation.

---

## Test Coverage

### Role C tests

| Module | Tests | Status |
|--------|-------|--------|
| `test_connector_evidence.py` | 6 | 6/6 passing |
| `test_factcheck_integration.py` | 10 | 10/10 passing |

### Full test suite (all roles)

```
68/68 PASSED (0 failures, 0 regressions)
├── test_connector_evidence.py:    6/6  (C)
├── test_evidence_chain.py:       10/10 (A)
├── test_evidence_audit.py:       14/14 (B)
├── test_factcheck.py:             4/4  (A)
├── test_traffic_light.py:        23/23 (B)
├── test_factcheck_integration.py: 11/11 (C)
```

---

## Minimal Integration Recipe for A/B

### To test C's integration end-to-end:

1. Start daemon: `ds --restart`
2. Upload a PDF via QQ bot with text: `/crossdisc_idea`
3. The agent will:
   - Call `mcp__factcheck__parse_pdf(pdf_path)` → get claims
   - Call `mcp__factcheck__verify_claim(...)` for each claim
   - Score claims with RYG traffic lights
   - Generate cross-discipline idea based on verified claims
4. Output appears as colored Markdown report via QQ

### To run C's tests:

```bash
pytest tests/test_factcheck_integration.py tests/test_connector_evidence.py -v
```

### To validate claim ID mapping:

```python
from deepscientist.factcheck import Claim
from deepscientist.factcheck.semantic_verifier import verify_claim

claim = Claim("C001", "Attention improves BLEU", ["[Vaswani 2017]"], "Attention Is All You Need")
vr = verify_claim(claim.claim_text, claim.cited_paper_title)
# IMPORTANT: vr.claim_id is empty — C must set it
vr.claim_id = claim.claim_id  # ← THIS IS THE CONTRACT
```

---

## Git Commits (Role C, current dev branch)

```
3b4fe68 feat: add Person C deliverables — crossdisc_idea skill, integration tests, report
86be57a chore: add DeepScientist runtime artifacts to .gitignore
f391aa9 feat: add PDF attachment evidence recording and cost optimization
dd3b0c7 fix: unhide image attachment paths so agent can analyse visual content
eed05ab fix: prevent MCP interact timeout by adding async dispatch fallback
2c88a13 fix: always emit connector_text entry to keep E00x numbering dense
4edd06c fix: resolve runner startup failures from disk-full deadlocks
41513be fix: disable duplicate QQ connector profile to prevent double message delivery
492ce7e fix: prevent MCP server duplication and disk-full hangs in runners
6fd2797 fix: add evidence recording hook to source daemon app.py (Role C)
542acd8 feat: add QQ connector multi-modal evidence recording and integration tests (Role C)
```
