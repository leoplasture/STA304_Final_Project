# Project A Person A Handoff Draft

## Scope (Person A Delivered)

Implemented files:

- `src/deepscientist/factcheck/__init__.py`
- `src/deepscientist/factcheck/claim_extractor.py`
- `src/deepscientist/factcheck/semantic_verifier.py`
- `src/deepscientist/factcheck/config/factcheck.example.yaml`
- `tests/test_factcheck.py`

Person A only delivered tool-layer logic and test coverage for extraction/verification.  
MCP registration, traffic-light scoring, rendering, and skill/prompt orchestration are not included in this handoff.

---

## Interface Contract for B/C

### Dataclasses (single source of truth)

Import from:

`deepscientist.factcheck`

```python
from deepscientist.factcheck import Claim, VerificationResult
```

`Claim`:

- `claim_id: str` (e.g., `C001`)
- `claim_text: str`
- `citation_markers: list[str]` (e.g., `["[Smith et al. 2023]"]`)
- `cited_paper_title: str` (resolved title or `""`)

`VerificationResult`:

- `claim_id: str` (currently empty from `verify_claim`, see known limits)
- `claim_text: str`
- `cited_paper: str`
- `verdict: str` in `{supported, contradicted, not_found, uncertain}`
- `evidence_level: str` (current behavior: `abstract_only`)
- `evidence_snippet: str`
- `confidence: float` in `[0.0, 1.0]`
- `notes: str`

### Tool functions

`parse_pdf(pdf_path: str) -> list[Claim]`

- Module: `deepscientist.factcheck.claim_extractor`
- Input: absolute/relative file path.
- Supported input in current implementation:
  - `.txt` / `.md`: fully supported.
  - `.pdf`: lightweight byte-decoding fallback parser.

`verify_claim(claim_text: str, cited_paper_title: str) -> VerificationResult`

- Module: `deepscientist.factcheck.semantic_verifier`
- Provider priority:
  1. Semantic Scholar (title + abstract)
  2. arXiv API (summary fallback)
  3. Crossref (metadata title fallback)

---

## Verdict and Confidence Semantics

Allowed verdict enum (must stay exact):

- `supported`
- `contradicted`
- `not_found`
- `uncertain`

Current verifier behavior:

- `not_found`: no usable evidence text from all providers.
- `supported` / `contradicted` / `uncertain`: heuristic lexical-overlap + polarity check.
- `confidence` is heuristic, bounded in `[0,1]`.

Recommendation for B:

- Keep traffic-light mapping based on this enum only.
- Do not depend on internal heuristic details.

---

## Config + Environment

Template file:

`src/deepscientist/factcheck/config/factcheck.example.yaml`

Environment variables used:

- `SEMANTIC_SCHOLAR_API_KEY` (optional)
- `FACTCHECK_HTTP_TIMEOUT_SECONDS` (optional override)

No secret keys are stored in repo.

---

## Error/Edge Behavior B/C Should Handle

`parse_pdf`:

- Raises `FileNotFoundError` when path not found.
- Returns `[]` when no eligible claim sentence extracted.

`verify_claim`:

- Never raises on provider failure in normal path; provider errors are swallowed and fallback chain continues.
- Returns `verdict=not_found` with `confidence=0.0` when all providers fail or no evidence text found.

---

## Known Limitations (Important for B/C Integration)

1. `verify_claim` currently does not receive `claim_id`, so returned `VerificationResult.claim_id` is empty string.
   - B/C should map claim id externally when batching.
2. `evidence_level` is currently always `abstract_only` in this version.
3. PDF parsing is fallback-grade (not full structured PDF extraction); `.txt/.md` inputs are much more stable for testing.
4. Verifier uses heuristic scoring now; this is MVP quality, not a final semantic entailment model.
5. No built-in retry/cache/rate-limit controller yet beyond simple provider fallback.

---

## Minimal Integration Recipe for B/C

1. B/C call `parse_pdf(pdf_path)` to get `list[Claim]`.
2. For each claim:
   - call `verify_claim(claim.claim_text, claim.cited_paper_title)`.
   - attach/mirror `claim.claim_id` into downstream result object.
3. B applies traffic-light rules using `verdict + confidence`.
4. C orchestrates this flow in skill/prompt and stage graph.

---

## Validation Status

Validated by:

- `tests/test_factcheck.py` (unit tests added)
- offline smoke execution (parse + verify with mocked provider responses)

Note:

- Full `uv run pytest` could not be executed in current environment due to network restrictions when syncing dependencies.

