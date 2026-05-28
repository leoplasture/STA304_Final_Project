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

**Critical integration rules:**
- `verify_claim` does NOT receive `claim_id`. The returned `VerificationResult.claim_id` will be empty.
- You MUST copy the `claim_id` from the original `Claim` into each `VerificationResult` before passing to scoring or rendering.
- Process claims sequentially to respect API rate limits.
- If `cited_paper_title` is empty, skip that claim and note it as unresolvable.

### Phase 3: Score and Render

For each verification result, determine the traffic-light color:

| verdict | confidence | color | meaning |
|---------|-----------|-------|---------|
| `supported` | ≥ 0.8 | 🟢 green | Claim is correct |
| `supported` | < 0.8 | 🟡 yellow | Partially supported |
| `contradicted` | ≥ 0.7 | 🔴 red | Claim is wrong |
| `contradicted` | < 0.7 | 🟡 yellow | Possibly wrong, uncertain |
| `uncertain` | any | 🟡 yellow | Cannot determine |
| `not_found` | any | 🟡 yellow | Cited paper not found |

Produce a FactCheck report with:
1. **Summary table**: green / yellow / red counts + final score (PASS / WARN / FAIL)
2. **Per-claim detail cards**: verdict, confidence, evidence snippet, and rationale
3. **Overall verdict**: if any red → FAIL; if >30% yellow → WARN; otherwise PASS

### Phase 4: Generate Cross-Discipline Idea

Based on the VERIFIED claims (green only), identify:
1. **Core contributions** of the source paper that are well-supported
2. **Gaps and opportunities** — what the paper didn't address
3. **Cross-discipline bridges** — how methods from this paper could apply to other domains
4. **Testable hypothesis** — a concrete new idea grounded in verified evidence

For any yellow claims, note them as "needs further verification" but do NOT base new ideas on them.
For any red claims, flag them as "citation errors — do not propagate."

### Phase 5: Output

Write the complete report (FactCheck results + cross-discipline ideas) to a file and send it to the user via `artifact.interact`. The report should include:

```markdown
# Cross-Discipline Research Idea Report

## 1. FactCheck Results
(Summary table + per-claim details from Phase 3)

## 2. Verified Evidence Base
(Only green claims — the reliable foundation)

## 3. Cross-Discipline Bridges
(Methods/insights from the paper applied to new domains)

## 4. Proposed Hypothesis
(A concrete, testable idea grounded in verified claims)

## 5. Caveats
(Yellow/red claims that need attention before acting on them)
```

## Notes

- This skill depends on the `factcheck` MCP namespace being available. It is auto-registered in modern runner configurations.
- The `mcp__factcheck__parse_pdf` tool handles `.pdf`, `.txt`, and `.md` inputs.
- API-based verification searches Semantic Scholar → arXiv → Crossref. Results may be abstract-only.
- Always copy `claim_id` from `Claim` to `VerificationResult` before scoring — the verifier does not do this.
