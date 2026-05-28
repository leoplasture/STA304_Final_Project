"""End-to-end integration tests for the factcheck pipeline — Role C."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deepscientist.factcheck import (
    Claim,
    FactCheckResult,
    ScoredClaimResult,
    VerificationResult,
)
from deepscientist.factcheck.claim_extractor import parse_pdf
from deepscientist.factcheck.factcheck_render import (
    render_claim_card,
    render_factcheck_markdown,
    render_factcheck_summary,
)
from deepscientist.factcheck.semantic_verifier import verify_claim
from deepscientist.factcheck.traffic_light import score_batch, score_verification


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_claim(
    claim_id: str = "C001",
    text: str = "Attention improves BLEU by 2.4 points",
    markers: list[str] | None = None,
    title: str = "Attention Is All You Need",
) -> Claim:
    return Claim(
        claim_id=claim_id,
        claim_text=text,
        citation_markers=markers or ["[Vaswani et al. 2017]"],
        cited_paper_title=title,
    )


def _make_verification(
    claim_id: str = "C001",
    verdict: str = "supported",
    confidence: float = 0.9,
) -> VerificationResult:
    return VerificationResult(
        claim_id=claim_id,
        claim_text="Attention improves BLEU",
        cited_paper="Vaswani et al. (2017)",
        verdict=verdict,
        evidence_level="abstract_only",
        evidence_snippet="The Transformer achieves state-of-the-art BLEU scores.",
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Test 1: Full pipeline — claim → verify → score → render
# ---------------------------------------------------------------------------

def test_full_pipeline_claim_to_rendered_report() -> None:
    """A green claim flows through score → batch → render without errors."""
    vr = _make_verification("C001", "supported", 0.9)
    scored = score_verification(vr)
    assert scored.color == "green"
    assert scored.label == "正确"

    batch = score_batch([vr], quest_id="q001", source_pdf="test.pdf")
    assert batch.total_claims == 1
    assert batch.green_count == 1
    assert batch.score == "PASS"

    md = render_factcheck_markdown(batch)
    assert "FactCheck" in md
    assert "PASS" in md
    assert vr.claim_text in md


# ---------------------------------------------------------------------------
# Test 2: Mixed verdicts produce correct aggregate score
# ---------------------------------------------------------------------------

def test_mixed_verdicts_aggregate_score() -> None:
    """1 green + 1 yellow + 1 red → FAIL (red present)."""
    results = [
        _make_verification("C001", "supported", 0.95),    # green
        _make_verification("C002", "not_found", 0.0),      # yellow
        _make_verification("C003", "contradicted", 0.85),  # red
    ]
    for i, vr in enumerate(results):
        vr.claim_id = f"C00{i+1}"
    batch = score_batch(results, quest_id="q002", source_pdf="mixed.pdf")
    assert batch.green_count == 1
    assert batch.yellow_count == 1
    assert batch.red_count == 1
    assert batch.score == "FAIL"
    assert len(batch.results) == 3


# ---------------------------------------------------------------------------
# Test 3: claim_id mapping contract (verify_claim returns empty claim_id)
# ---------------------------------------------------------------------------

def test_claim_id_must_be_mapped_externally() -> None:
    """verify_claim returns empty claim_id; C must copy it from Claim."""
    claim = _make_claim("C005", "Test claim", title="Test Paper")
    vr = verify_claim(claim.claim_text, claim.cited_paper_title)
    # Important: the verifier does NOT set claim_id
    assert vr.claim_id == ""
    # C must map it
    vr.claim_id = claim.claim_id
    assert vr.claim_id == "C005"


# ---------------------------------------------------------------------------
# Test 4: Empty claim list → N/A score
# ---------------------------------------------------------------------------

def test_empty_claims_produces_na_score() -> None:
    """An empty batch produces a valid N/A result (no crash)."""
    batch = score_batch([], quest_id="q003", source_pdf="empty.pdf")
    assert batch.total_claims == 0
    assert batch.score == "N/A"
    md = render_factcheck_markdown(batch)
    assert "N/A" in md or "no claims" in md.lower()


# ---------------------------------------------------------------------------
# Test 5: PDF parsing with a known-good text file (txt path is stable)
# ---------------------------------------------------------------------------

def test_parse_pdf_from_text_file(tmp_path: Path) -> None:
    """parse_pdf on a .txt file extracts at least one claim."""
    txt = tmp_path / "paper.txt"
    txt.write_text(
        "We propose a novel method. "
        "Our approach outperforms the baseline by 5.2 points [Smith et al. 2020]. "
        "Previous work [Jones 2019] also reported similar findings.",
        encoding="utf-8",
    )
    claims = parse_pdf(str(txt))
    assert isinstance(claims, list)
    # At least one claim-like sentence should be extracted
    assert any("[Smith et al. 2020]" in c.claim_text or "[Jones 2019]" in c.claim_text
               for c in claims), f"Expected citation markers in claims, got {len(claims)} claims"


# ---------------------------------------------------------------------------
# Test 6: Rendering functions never raise
# ---------------------------------------------------------------------------

def test_rendering_functions_never_raise() -> None:
    """All render functions handle edge cases without exceptions."""
    # Empty result
    empty = score_batch([], quest_id="q", source_pdf="none.pdf")
    assert render_factcheck_markdown(empty)
    assert render_factcheck_summary(empty)

    # Single claim of each color
    for verdict, conf, color in [
        ("supported", 0.95, "green"),
        ("not_found", 0.0, "yellow"),
        ("contradicted", 0.85, "red"),
    ]:
        vr = _make_verification("C001", verdict, conf)
        scored = score_verification(vr)
        assert scored.color == color
        card = render_claim_card(scored, index=0)
        assert scored.claim_text in card


# ---------------------------------------------------------------------------
# Test 7: Full integration — parse + verify + score + render
# ---------------------------------------------------------------------------

def test_end_to_end_factcheck_integration(tmp_path: Path) -> None:
    """Full pipeline: write a paper to .txt, parse claims, verify, score, render."""
    # 1. Create a test paper with known claims
    paper = tmp_path / "test_paper.txt"
    paper.write_text(
        "Abstract\n\n"
        "We introduce a new attention mechanism. "
        "Our method achieves 95.3% accuracy, outperforming PreviousNet by 3.2 points [Smith 2021]. "
        "The training converges in half the time of baseline models [Jones 2020]. "
        "All experiments were conducted on standard benchmarks.\n\n"
        "Introduction\n\n"
        "Deep learning has revolutionized NLP [Vaswani et al. 2017]. "
        "Recent advances in transformer architectures have pushed state-of-the-art further.",
        encoding="utf-8",
    )

    # 2. Parse claims
    claims = parse_pdf(str(paper))
    assert len(claims) > 0, "Expected at least 1 claim from the paper"

    # 3. Verify each claim
    results: list[VerificationResult] = []
    for claim in claims:
        vr = verify_claim(claim.claim_text, claim.cited_paper_title)
        # C must map claim_id
        vr.claim_id = claim.claim_id
        results.append(vr)

    assert len(results) == len(claims)

    # 4. Score batch
    batch = score_batch(results, quest_id="integration_test", source_pdf=str(paper))
    assert batch.total_claims == len(results)
    assert batch.green_count + batch.yellow_count + batch.red_count == batch.total_claims

    # 5. Render
    markdown = render_factcheck_markdown(batch)
    assert "FactCheck" in markdown
    assert len(markdown) > 100

    summary = render_factcheck_summary(batch)
    assert len(summary) > 10

    # 6. Verify JSON-serializable (for MCP transport)
    json.dumps(batch.results, default=str)


# ---------------------------------------------------------------------------
# Test 8: PDF file not found → FileNotFoundError
# ---------------------------------------------------------------------------

def test_parse_pdf_file_not_found() -> None:
    """Non-existent path raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        parse_pdf("/nonexistent/path/paper.pdf")


# ---------------------------------------------------------------------------
# Test 9: Skill file exists and is valid
# ---------------------------------------------------------------------------

def test_crossdisc_idea_skill_exists() -> None:
    """The crossdisc_idea SKILL.md exists and has required frontmatter."""
    from pathlib import Path

    skill_path = Path(__file__).parent.parent / "src" / "skills" / "crossdisc_idea" / "SKILL.md"
    if not skill_path.exists():
        pytest.skip("crossdisc_idea SKILL.md not deployed yet")

    content = skill_path.read_text(encoding="utf-8")
    assert "---" in content, "SKILL.md must have frontmatter"
    assert "name:" in content
    assert "skill_role:" in content
    assert "crossdisc_idea" in content or "factcheck" in content.lower()


# ---------------------------------------------------------------------------
# Test 10: Claim → VerificationResult → ScoredClaimResult data integrity
# ---------------------------------------------------------------------------

def test_data_integrity_through_pipeline() -> None:
    """claim_text and cited_paper survive the full pipeline unchanged."""
    claim = _make_claim("C010", "X improves Y by 10%", title="The X Paper")
    vr = verify_claim(claim.claim_text, claim.cited_paper_title)
    vr.claim_id = claim.claim_id

    assert vr.claim_text == claim.claim_text
    assert vr.cited_paper is not None  # verifier may set a resolved name

    scored = score_verification(vr)
    assert scored.claim_id == "C010"
    assert scored.claim_text == claim.claim_text
    assert scored.verdict == vr.verdict
    assert scored.confidence == vr.confidence
    assert scored.color in ("green", "yellow", "red")
    assert scored.label in ("正确", "不确定", "错误")
