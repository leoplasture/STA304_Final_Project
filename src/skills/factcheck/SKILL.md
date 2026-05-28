# FactCheck Skill

## Overview

Verify literature citations in research ideas and reports. Input a PDF or plain-text report, extract factual claims with their citations, verify each claim against the cited paper, and produce a red/yellow/green (RYG) fact-check report.

## When to Use

- User uploads a PDF and asks "check this paper" or "verify the citations"
- After generating a research idea, to verify its references
- Before submitting a report, to audit citation quality
- Any time the user wants to know if cited literature actually supports the claims

## Flow

### Step 1: Parse the source

If input is a PDF, extract claims first:

```
mcp__factcheck__parse_pdf(pdf_path="<absolute path to PDF>")
```

This returns a list of structured claims, each with a `claim_id`, `claim_text`, `citation_markers`, and `cited_paper_title`.

### Step 2: Verify each claim

For each claim, verify it against the cited paper:

```
mcp__factcheck__verify_claim(
    claim_text="<claim text>",
    cited_paper_title="<paper title>"
)
```

**Important notes:**
- `verify_claim` does **not** receive `claim_id` internally. You must track the mapping between `claim_id` and the result yourself. The returned `VerificationResult.claim_id` will be empty — fill it in before passing to rendering.
- The verifier searches Semantic Scholar → arXiv → Crossref, in that order.
- Evidence level is `abstract_only` in the current version; full-text verification may be added later.
- If all providers fail, the verdict will be `not_found` with `confidence=0.0`.

### Step 3: Report results

After all claims are verified, produce a colored report with:

1. A summary table (green / yellow / red counts)
2. Per-claim details with verdict, confidence, and rationale

## Verdict Interpretation

| Color | Meaning | Action |
|-------|---------|--------|
| 🟢 Green | Claim is supported by the cited paper | No action — citation is correct |
| 🟡 Yellow | Claim is uncertain or cannot be confirmed | Flag for review; may need a better citation |
| 🔴 Red | Claim is contradicted by the cited paper | Citation error — fix or remove the claim |

## Output Format

Use a Markdown table for the summary, followed by per-claim detail cards:

```markdown
## FactCheck Report

### Summary
| 🟢 Correct | 🟡 Uncertain | 🔴 Wrong | Total | Score |
|------------|--------------|----------|-------|-------|
| 3 | 2 | 1 | 6 | FAIL |

### Per-Claim Details
...
```
