---
name: crossdisc_idea
description: Generate cross-discipline research ideas from uploaded PDFs with automatic fact-checking. Verifies all cited literature claims before proposing new directions.
skill_role: stage
skill_order: 55
---

# Cross-Discipline Idea with FactCheck

Use this skill when a user uploads a PDF from any discipline and wants the agent to:
1. Extract and verify all literature claims in the PDF
2. Generate cross-discipline research ideas grounded in verified evidence

This skill sits between `scout` and `idea` in the stage graph (order 55, between scout at 50 and idea at 60).

## Flow

### Phase 0: Receive PDF

The user uploads a PDF via QQ. The attachment path is available in the current turn's attachment block as `raw_binary_path`. If no PDF path is available, ask the user to upload one.

### Phase 1: Parse Claims

Call `mcp__factcheck__parse_pdf` to extract claims from the PDF:

```
mcp__factcheck__parse_pdf(pdf_path="<absolute path to PDF>")
```

This returns a list of `Claim` objects, each with:
- `claim_id` (e.g. "C001")
- `claim_text` (the factual statement)
- `citation_markers` (e.g. ["[Smith et al. 2023]"])
- `cited_paper_title` (resolved paper title, or "" if unresolved)

If the list is empty, report that no structured claims could be extracted and fall back to manual review.

### Phase 2: Verify Each Claim

For each claim, verify it against its cited paper:

```
mcp__factcheck__verify_claim(
    claim_text="<claim text>",
    cited_paper_title="<paper title>"
)
```

**CRITICAL — claim_id mapping (MUST DO, NOT OPTIONAL):**

You can pass `claim_id` directly to the MCP tool and it will be preserved:

```
mcp__factcheck__verify_claim(
    claim_text="<claim text>",
    cited_paper_title="<paper title>",
    claim_id="<claim_id>"    # <-- PASS THE CLAIM ID HERE
)
```

If you forget, manually copy it from the original Claim:

```
vr.claim_id = claim.claim_id   # fallback if claim_id was not passed
```

**Other rules:**
- Process claims sequentially to respect API rate limits.
- **Do NOT skip claims with empty `cited_paper_title`.** The verifier now handles empty titles by searching Semantic Scholar with keywords extracted from the claim text. Results may be uncertain, but the pipeline must still run.
- **After verifying ALL claims, you MUST proceed to Phase 3** — even if every result was `not_found` or `uncertain`. A report with 🟡 WARN is the correct honest output, not a skipped pipeline.

### Phase 3: Score and Render

**You MUST call the FactCheck MCP tools for scoring and rendering. Do NOT compute scores manually.**

After collecting all VerificationResults (with claim_id already mapped), call:

```
# Step 1: Score all verification results and aggregate
mcp__factcheck__score_batch(
    results=<list of verify_claim dict results>,
    quest_id="<quest_id>",
    source_pdf="<pdf path>"
)
```

Returns a dict with: `total_claims`, `green_count`, `yellow_count`, `red_count`, `score` (PASS/WARN/FAIL/N/A), and `results` (each with `color`, `label`, `rationale`).

```
# Step 2: Render the full colored Markdown report
mcp__factcheck__render_report(batch_result=<dict from score_batch>)
```

Returns a formatted Markdown string with 🟢🟡🔴 summary table + per-claim detail cards. Use this as Section 1 of the final report.

```
# Step 3 (optional): Get a compact one-line summary
mcp__factcheck__render_summary(batch_result=<dict from score_batch>)
```

Returns a short status line like `🟡 WARN — 0 green, 3 yellow, 0 red (3 claims)`.

The scoring rules (built into `score_batch`):

| verdict | confidence | color | label |
|---------|-----------|-------|-------|
| `supported` | ≥ 0.8 | 🟢 green | 正确 |
| `supported` | < 0.8 | 🟡 yellow | 不确定 |
| `contradicted` | ≥ 0.7 | 🔴 red | 错误 |
| `contradicted` | < 0.7 | 🟡 yellow | 不确定 |
| `uncertain` | any | 🟡 yellow | 不确定 |
| `not_found` | any | 🟡 yellow | 不确定 |

The batch score is automatically:
- `0 total_claims` → `"N/A"`
- `red_count > 0` → `"FAIL"`
- `yellow_count > total_claims * 0.3` → `"WARN"`
- otherwise → `"PASS"`

### Phase 4: Generate Cross-Discipline Idea

Based on the VERIFIED claims (green only), identify:
1. **Core contributions** of the source paper that are well-supported
2. **Gaps and opportunities** — what the paper didn't address
3. **Cross-discipline bridges** — how methods from this paper could apply to other domains
4. **Testable hypothesis** — a concrete new idea grounded in verified evidence

For any yellow claims, note them as "needs further verification" but do NOT base new ideas on them.
For any red claims, flag them as "citation errors — do not propagate."

**Wording discipline (MUST FOLLOW):**

The report's language strength MUST NOT exceed what the FactCheck results justify.
Use hedging language whenever the evidence is incomplete:

| Instead of | Use |
|------------|-----|
| perfectly matches / fully supports | partially aligns with / provides partial support for |
| genuinely novel / clearly demonstrates | potentially novel / suggests / indicates |
| strongest evidence | relatively stronger evidence |
| This is a genuinely novel direction | This may indicate a potentially novel direction, but further comparison with related work is needed |

When the FactCheck score is WARN or FAIL, do NOT claim the idea is "strongly supported" or "verified."
Use phrases like "preliminary verification suggests" and "further manual review is recommended."

### Phase 5: Output (Strict State Machine)

This phase is a 5-state linear pipeline. Each state executes **exactly once**. After transitioning to the next state, you MUST NOT re-enter any previous state. If an exit check fails, retry the CURRENT state — do not skip ahead.

```
STATE_1 → STATE_2 → STATE_3 → STATE_4 → STATE_5
  Score    Render   Record    Memory    Deliver
```

---

#### STATE 1 — Score (enter ONCE)

Call `mcp__factcheck__score_batch` with ALL verification results from Phase 3:

```
mcp__factcheck__score_batch(
    results=<list of ALL verify_claim result dicts>,
    quest_id="<quest_id>",
    source_pdf="<pdf path>"
)
```

**Exit check — confirm ALL of these before leaving State 1:**
- [ ] The returned object has `score` field equal to one of: `PASS`, `WARN`, `FAIL`, `N/A`
- [ ] The returned object has `total_claims` matching the number of claims parsed in Phase 1
- [ ] The returned object has `green_count`, `yellow_count`, `red_count` that sum to `total_claims`

If ANY check fails: the `score_batch` call was incomplete. Re-call with all results. Do NOT compute scores manually.

**After passing exit checks:** Store the result as `batch_result`. Proceed to State 2. **Never call score_batch again for this report.**

---

#### STATE 2 — Render (enter ONCE)

Call `mcp__factcheck__render_report` with the batch_result from State 1:

```
mcp__factcheck__render_report(batch_result=<dict from State 1>)
```

**Exit check — confirm ALL of these before leaving State 2:**
- [ ] The returned markdown string contains at least one of: 🟢, 🟡, 🔴
- [ ] The returned markdown string is non-empty (≥ 200 characters)

If ANY check fails: the render call was incomplete. Re-call `render_report` with the same `batch_result`. Do NOT hand-write the factcheck table.

**After passing exit checks:** Store the result as `rendered_report`. Proceed to State 3.

---

#### STATE 3 — Record Evidence (enter ONCE)

Call `mcp__artifact__record` to persist the FactCheck results. The `body` parameter MUST be the complete `batch_result` JSON string — do NOT truncate or summarize:

```
mcp__artifact__record(
    kind="report",
    title="FactCheck: <paper title>",
    body=<JSON.stringify(batch_result) — FULL object, not a summary>,
    metadata={
        "total_claims": <N>,
        "green": <N>, "yellow": <N>, "red": <N>,
        "score": "<PASS|WARN|FAIL|N/A>",
        "source_pdf": "<path to PDF>",
        "extraction_method": "parse_pdf"
    }
)
```

**Exit check — confirm ALL of these before leaving State 3:**
- [ ] The returned status is `"ok"` (NOT `"calling"`, `"pending"`, or `"error"`)
- [ ] The `body` you passed is ≥ 500 characters (a full batch_result, not a stub)

If ANY check fails: the record call was incomplete. Check the `body` parameter and re-call. Do NOT proceed to State 4 with an empty or truncated evidence record.

**After passing exit checks:** Proceed to State 4.

**CRITICAL — do NOT call artifact.record again:**
- You already persisted the evidence. There is exactly ONE evidence record per quest.
- Do NOT call `artifact.record` a second time — not with `kind="report"`, not with any other `kind`, not with a different `title`.
- Even if you think a second record is needed — it is NOT. Stop after one successful call.

---

#### STATE 4 — Write Memory (enter ONCE)

Call `mcp__memory__write` with the FULL report content. The `kind` MUST be `"episodes"` (plural). Valid memory kinds: papers, ideas, decisions, episodes, knowledge, templates.

```
mcp__memory__write(
    kind="episodes",
    title="FactCheck Experiment: <paper title>",
    markdown=<the FULL report content — see State 5 template below>,
    scope="quest",
    metadata={
        "quest_id": "<quest_id>",
        "timestamp": "<ISO timestamp>",
        "paper_title": "<paper title>",
        "claims_parsed": <N>,
        "verification_results": {
            "green": <N>, "yellow": <N>, "red": <N>,
            "score": "<PASS|WARN|FAIL|N/A>"
        },
        "artifacts": ["crossdisc-idea-report.md"],
        "extraction_method": "parse_pdf",
        "verifier_notes": "abstract-only verification; false positives possible on title mismatch"
    }
)
```

**Exit check — confirm ALL of these before leaving State 4:**
- [ ] The `markdown` parameter is non-empty and ≥ 500 characters
- [ ] The `markdown` contains the string `"## 1. FactCheck Results"` (or equivalent section header)

If ANY check fails: the memory write was incomplete. Re-call with the full report content in the `markdown` field. Do NOT proceed to State 5 with an empty memory entry.

**After passing exit checks:** Proceed to State 5. **Never call memory.write for this quest again.**

---

#### STATE 5 — Write Report File & Deliver

Only after States 1-4 have passed all exit checks, write the complete report to `crossdisc-idea-report.md` and send to the user via `artifact.interact(kind="milestone", ...)`.

The report MUST use `rendered_report` (from State 2) as Section 1. Do NOT replace it with a plain-text table.

```markdown
# Cross-Discipline Research Idea Report

**Paper**: <resolved paper title>
**FactCheck Score**: <PASS|WARN|FAIL> — 🟢 N correct, 🟡 N uncertain, 🔴 N wrong (N claims total)

## 1. FactCheck Results
(Insert rendered_report from State 2 here — includes 🟢🟡🔴 summary + per-claim detail cards)

## 2. Evidence Chain Table
(Always include this table, mapping each verified claim to an E-series evidence ID)

**Evidence ID mapping rule:** Map each claim ID to an evidence ID using the format `E{NNN}` where NNN matches the claim number. C001 → E001, C002 → E002, etc. For image/pdf attachments, use the evidence IDs already recorded in the evidence_store (e.g., E012-img, E018-pdf). This ensures all report evidence references are traceable through the evidence chain audit system, which recognizes `[E001]`, `[E001-img]`, and `[E001-pdf]` patterns.

| Evidence ID | Claim ID | Claim Summary | Source | Extraction Method | Verdict | Traffic Light |
|-------------|----------|---------------|--------|-------------------|---------|---------------|
| E001 | C001 | FL enables collaborative training | Semantic Scholar (abstract) | parse_pdf | supported | 🟢 |
| E002 | C002 | MHPFL enables heterogeneous models | arXiv (abstract) | parse_pdf | not_found | 🟡 |
| (if parser failed) | C00X | — | — | bash_fallback | — | ⚪ |

## 3. Verified Evidence Base
(Only 🟢 green claims — the reliable foundation for Phase 4)

## 4. Cross-Discipline Bridges
(Methods/insights from the paper applied to new domains)

## 5. Proposed Hypothesis
(A concrete, testable idea grounded in verified claims)

## 6. Caveats
(🟡 Yellow / 🔴 red claims that need attention. Use hedging language per Phase 4.)
```

---

#### State Machine Rules (CRITICAL)

- **No re-entry**: Once a state's exit checks pass, do NOT return to it. If you catch yourself about to call `score_batch` a second time, STOP — you already scored.
- **No kind-switching**: `artifact.record` uses `kind="report"` exactly once. Do not call it again with any kind — the evidence is already stored. The artifact server's semantic deduplication will suppress duplicate `kind="report"` records with the same content anyway.
- **No skipping**: Do not proceed to State N+1 until State N's exit checks are all confirmed.
- **Failed exit check → retry SAME state**: If the exit check fails, fix the problem and re-call the SAME tool. Do not jump to a different state to "work around" the failure.
- **No manual workarounds**: Do not compute scores, write factcheck tables, or summarize batch_results by hand. Always use the MCP tools for their intended purpose.

## Notes

- This skill depends on the `factcheck` MCP namespace being available. It is auto-registered in modern runner configurations.
- The `mcp__factcheck__parse_pdf` tool handles `.pdf`, `.txt`, and `.md` inputs.
- API-based verification searches Semantic Scholar → arXiv → Crossref. Results may be abstract-only.
- Claim ID mapping is done by passing `claim_id` to `verify_claim`; verify_claim returns it back unchanged.
- If `parse_pdf` fails and bash_exec fallback is used, record `extraction_method: bash_fallback` in the evidence chain table.
- Memory kind MUST be `episodes` (plural), not `episode` (singular). Using singular will raise ValueError.
