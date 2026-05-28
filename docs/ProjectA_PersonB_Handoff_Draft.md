# Project A Person B Handoff Draft

## Scope (Person B Delivered)

Implemented files:

- `src/deepscientist/factcheck/__init__.py` — extended with `ScoredClaimResult` + `FactCheckResult` (merged with A's `Claim` + `VerificationResult`)
- `src/deepscientist/factcheck/traffic_light.py` — RYG scoring
- `src/deepscientist/factcheck/factcheck_render.py` — colored Markdown rendering
- `src/skills/factcheck/SKILL.md` — model-facing factcheck prompt
- `tests/test_traffic_light.py` — 23 tests for scoring + rendering

Modified files (MCP + runner registration):

- `src/deepscientist/mcp/server.py` — added `build_factcheck_server()` with `parse_pdf` and `verify_claim` tools
- `src/deepscientist/runners/base.py` — `DEFAULT_BUILTIN_MCP_SERVER_NAMES` includes `"factcheck"`
- `src/deepscientist/prompts/builder.py` — built-in namespaces include `"factcheck"`
- `src/deepscientist/acp/envelope.py` — mcp_servers list includes `{"name": "factcheck", ...}`

---

## Interface Contract for C

### Shared Dataclasses

Import from:

`deepscientist.factcheck`

```python
from deepscientist.factcheck import (
    Claim,                # A's — input from parse_pdf
    VerificationResult,   # A's — output from verify_claim
    ScoredClaimResult,    # B's — scored with color/label
    FactCheckResult,      # B's — aggregated batch result
)
```

`ScoredClaimResult`:

- `claim_id: str`
- `claim_text: str`
- `cited_paper: str`
- `verdict: str` — `supported | contradicted | not_found | uncertain`
- `confidence: float` — `[0.0, 1.0]`
- `color: str` — `"green" | "yellow" | "red"`
- `label: str` — `"正确" | "不确定" | "错误"`
- `rationale: str` — human-readable reason for the score

`FactCheckResult`:

- `quest_id: str`
- `source_pdf: str`
- `total_claims: int`
- `green_count: int`
- `yellow_count: int`
- `red_count: int`
- `results: list[ScoredClaimResult]`
- `score: str` (property) — `"PASS" | "WARN" | "FAIL" | "N/A"`

### Scoring Functions

`score_verification(vr: VerificationResult) -> ScoredClaimResult`

- Module: `deepscientist.factcheck.traffic_light`
- Maps `(verdict, confidence)` → RYG color.
- Covers all verdict × confidence combinations (no fallthrough).

`score_batch(results: list[VerificationResult], *, quest_id: str = "", source_pdf: str = "") -> FactCheckResult`

- Scores a list of VerificationResults, aggregates into FactCheckResult.
- **Important**: `verify_claim` returns empty `claim_id`. C must populate `VerificationResult.claim_id` from the corresponding `Claim.claim_id` **before** calling `score_batch`.

### Rendering Functions

`render_factcheck_markdown(result: FactCheckResult) -> str`

- Module: `deepscientist.factcheck.factcheck_render`
- Full colored Markdown report with summary table + per-claim detail cards.
- Suitable for QQ Bot output / final report.

`render_factcheck_summary(result: FactCheckResult) -> str`

- Compact one-line summary with emoji. Use for inline status updates.

`render_claim_card(scored: ScoredClaimResult, *, index: int = 0) -> str`

- Single claim card. Use inside custom report loops if needed.

### MCP Tools (already registered)

`mcp__factcheck__parse_pdf(pdf_path="<path>")`

- Returns `list[dict]` with keys: `claim_id`, `claim_text`, `citation_markers`, `cited_paper_title`
- Registered in `build_factcheck_server()` → available in all runners automatically.

`mcp__factcheck__verify_claim(claim_text="...", cited_paper_title="...")`

- Returns `dict` with keys: `claim_id`, `claim_text`, `cited_paper`, `verdict`, `evidence_level`, `evidence_snippet`, `confidence`, `notes`
- `claim_id` in response is always empty — C must map it externally.

---

## RYG Scoring Rules (traffic_light.py)

| verdict | confidence | color | label |
|---------|-----------|-------|-------|
| `supported` | ≥ 0.8 | `green` | `正确` |
| `supported` | < 0.8 | `yellow` | `不确定` |
| `contradicted` | ≥ 0.7 | `red` | `错误` |
| `contradicted` | < 0.7 | `yellow` | `不确定` |
| `uncertain` | any | `yellow` | `不确定` |
| `not_found` | any | `yellow` | `不确定` |
| unknown | any | `yellow` | `不确定` |

`FactCheckResult.score` property:

- `0 total_claims` → `"N/A"`
- `red_count > 0` → `"FAIL"`
- `yellow_count > total_claims * 0.3` → `"WARN"`
- otherwise → `"PASS"`

---

## Error/Edge Behavior C Should Handle

`score_verification`:

- Never raises. Unknown verdict values fall back to yellow.
- Input `VerificationResult` fields are passed through unchanged to `ScoredClaimResult`.

`score_batch`:

- Empty list returns `FactCheckResult` with `total_claims=0`, all counts zero, score `"N/A"`.

Rendering functions:

- Never raise. Empty results produce human-readable "no claims" messages.
- Unknown `color` values render as ⚪ (fallback emoji).

MCP tools:

- Both tools return error dicts (not raise exceptions) when A's factcheck module is not deployed.
- `verify_claim` returns `verdict=not_found, confidence=0.0` on ImportError.

---

## Known Limitations

1. `score_batch` does not auto-populate `claim_id`. C must map claim IDs from A's `parse_pdf` output before calling `score_batch`.
2. Rendering produces pure Markdown. HTML/CSS color spans (`<span style="color:...">`) are included but may not render in plain-text QQ messages. The emoji-based rendering (🟢🟡🔴) works universally.
3. `FactCheckResult.score` is a simple heuristic (FAIL on any red, WARN on >30% yellow). Edge cases with very small claim counts may give unintuitive results.
4. MCP tools are registered but depend on A's `claim_extractor.py` and `semantic_verifier.py` being deployed. Until then, they return graceful error dicts.

---

## Minimal Integration Recipe for C

1. In `crossdisc_idea/SKILL.md`, orchestrate the flow:
   - Call `mcp__factcheck__parse_pdf(pdf_path)` → get `list[Claim]`
   - For each claim, call `mcp__factcheck__verify_claim(claim.claim_text, claim.cited_paper_title)` → get `VerificationResult`
   - Copy `claim.claim_id` into each `VerificationResult.claim_id`
   - (Optional) Use `score_batch()` and `render_factcheck_markdown()` to produce a pre-rendered report
2. In `prompts/builder.py`, register factcheck in the stage graph before `idea`:
   - The namespace `"factcheck"` is already in `built_in_namespaces` (line 196). No action needed unless C wants to gate it per-profile.
3. Run `tests/test_factcheck_integration.py` end-to-end with a known-bad PDF.

---

## Validation Status

- `tests/test_traffic_light.py` — 23 tests, all passing (verified locally via `uv run pytest tests/test_traffic_light.py`)
- Scoring rules validated against all 7 verdict × confidence branches
- Rendering output manually inspected for correct emoji and structure
- MCP registration confirmed in all 4 integration points (server.py, base.py, builder.py, envelope.py)
