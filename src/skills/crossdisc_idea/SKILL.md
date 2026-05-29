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

### Phase 5: Output

Write the complete report to a file and send it to the user via `artifact.interact`.

**The FactCheck section MUST use the rendered output from `mcp__factcheck__render_report(batch_result)`** — it contains properly colored RYG emoji (🟢🟡🔴) and formatted claim cards. Do NOT replace it with a plain-text table.

Report structure:

```markdown
# Cross-Discipline Research Idea Report

## 1. FactCheck Results
(Insert mcp__factcheck__render_report output here — includes 🟢🟡🔴 summary + per-claim cards)

## 2. Verified Evidence Base
(Only 🟢 green claims — the reliable foundation)

## 3. Cross-Discipline Bridges
(Methods/insights from the paper applied to new domains)

## 4. Proposed Hypothesis
(A concrete, testable idea grounded in verified claims)

## 5. Caveats
(🟡 Yellow / 🔴 red claims that need attention before acting on them)
```

## Notes

- This skill depends on the `factcheck` MCP namespace being available. It is auto-registered in modern runner configurations.
- The `mcp__factcheck__parse_pdf` tool handles `.pdf`, `.txt`, and `.md` inputs.
- API-based verification searches Semantic Scholar → arXiv → Crossref. Results may be abstract-only.
- Always copy `claim_id` from `Claim` to `VerificationResult` before scoring — the verifier does not do this.
