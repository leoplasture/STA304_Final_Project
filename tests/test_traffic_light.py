"""Tests for traffic_light scoring logic and RYG rendering."""

import pytest
from deepscientist.factcheck import (
    FactCheckResult,
    ScoredClaimResult,
    VerificationResult,
)
from deepscientist.factcheck.traffic_light import score_batch, score_verification
from deepscientist.factcheck.factcheck_render import (
    render_claim_card,
    render_factcheck_markdown,
    render_factcheck_summary,
)


# ── VerificationResult fixtures ──────────────────────────────────────────

def _vr(verdict: str, confidence: float, **kwargs) -> VerificationResult:
    defaults = {
        "claim_id": "C001",
        "claim_text": "Attention improves BLEU by 2.4 points.",
        "cited_paper": "Smith et al. (2023)",
        "evidence_level": "abstract_only",
        "evidence_snippet": "BLEU improved by 2.4 after adding attention.",
    }
    defaults.update(kwargs)
    return VerificationResult(verdict=verdict, confidence=confidence, **defaults)


# ── score_verification tests ─────────────────────────────────────────────

class TestScoreVerification:
    def test_supported_high_confidence_green(self):
        result = score_verification(_vr("supported", 0.9))
        assert result.color == "green"
        assert result.label == "正确"

    def test_supported_exact_threshold_green(self):
        result = score_verification(_vr("supported", 0.8))
        assert result.color == "green"
        assert result.label == "正确"

    def test_supported_low_confidence_yellow(self):
        result = score_verification(_vr("supported", 0.6))
        assert result.color == "yellow"
        assert result.label == "不确定"

    def test_supported_zero_confidence_yellow(self):
        result = score_verification(_vr("supported", 0.0))
        assert result.color == "yellow"

    def test_contradicted_high_confidence_red(self):
        result = score_verification(_vr("contradicted", 0.9))
        assert result.color == "red"
        assert result.label == "错误"

    def test_contradicted_exact_threshold_red(self):
        result = score_verification(_vr("contradicted", 0.7))
        assert result.color == "red"

    def test_contradicted_low_confidence_yellow(self):
        result = score_verification(_vr("contradicted", 0.5))
        assert result.color == "yellow"
        assert result.label == "不确定"

    def test_uncertain_yellow(self):
        result = score_verification(_vr("uncertain", 0.5))
        assert result.color == "yellow"
        assert result.label == "不确定"

    def test_not_found_yellow(self):
        result = score_verification(_vr("not_found", 0.0))
        assert result.color == "yellow"
        assert result.label == "不确定"

    def test_unknown_verdict_fallback_yellow(self):
        result = score_verification(_vr("bogus", 0.99))
        assert result.color == "yellow"

    def test_preserves_input_fields(self):
        vr = _vr("supported", 0.95, claim_id="C042", claim_text="X causes Y.")
        result = score_verification(vr)
        assert result.claim_id == "C042"
        assert result.claim_text == "X causes Y."
        assert result.cited_paper == "Smith et al. (2023)"
        assert result.verdict == "supported"
        assert result.confidence == 0.95


# ── score_batch tests ────────────────────────────────────────────────────

class TestScoreBatch:
    def test_empty_batch(self):
        result = score_batch([])
        assert result.total_claims == 0
        assert result.green_count == 0
        assert result.yellow_count == 0
        assert result.red_count == 0
        assert result.score == "N/A"

    def test_all_green_passes(self):
        vrs = [
            _vr("supported", 0.9, claim_id="C001"),
            _vr("supported", 0.85, claim_id="C002"),
        ]
        result = score_batch(vrs, quest_id="Q1", source_pdf="test.pdf")
        assert result.total_claims == 2
        assert result.green_count == 2
        assert result.yellow_count == 0
        assert result.red_count == 0
        assert result.score == "PASS"
        assert result.quest_id == "Q1"
        assert result.source_pdf == "test.pdf"

    def test_any_red_fails(self):
        vrs = [
            _vr("supported", 0.9),
            _vr("contradicted", 0.8),
        ]
        result = score_batch(vrs)
        assert result.red_count == 1
        assert result.score == "FAIL"

    def test_many_yellow_warns(self):
        vrs = [
            _vr("supported", 0.7),
            _vr("uncertain", 0.5),
            _vr("not_found", 0.0),
            _vr("supported", 0.9),
            _vr("contradicted", 0.3),
        ]
        result = score_batch(vrs)
        assert result.yellow_count == 4
        assert result.yellow_count > result.total_claims * 0.3
        assert result.score == "WARN"

    def test_few_yellow_passes(self):
        vrs = [
            _vr("supported", 0.9),
            _vr("supported", 0.9),
            _vr("uncertain", 0.5),
            _vr("supported", 0.9),
            _vr("supported", 0.9),
            _vr("supported", 0.9),
        ]
        result = score_batch(vrs)
        assert result.yellow_count == 1
        assert result.yellow_count <= result.total_claims * 0.3
        assert result.score == "PASS"


# ── Rendering tests ──────────────────────────────────────────────────────

class TestRenderClaimCard:
    def test_green_card(self):
        scored = ScoredClaimResult(
            claim_id="C001",
            claim_text="X improves Y.",
            cited_paper="Paper A",
            verdict="supported",
            confidence=0.9,
            color="green",
            label="正确",
            rationale="good",
        )
        md = render_claim_card(scored)
        assert "🟢" in md
        assert "正确" in md
        assert "X improves Y." in md
        assert "Paper A" in md

    def test_red_card(self):
        scored = ScoredClaimResult(
            claim_id="C002",
            claim_text="Z breaks W.",
            cited_paper="Paper B",
            verdict="contradicted",
            confidence=0.85,
            color="red",
            label="错误",
            rationale="bad",
        )
        md = render_claim_card(scored)
        assert "🔴" in md
        assert "错误" in md

    def test_yellow_card(self):
        scored = ScoredClaimResult(
            claim_id="C003",
            claim_text="A causes B.",
            cited_paper="Paper C",
            verdict="uncertain",
            confidence=0.4,
            color="yellow",
            label="不确定",
        )
        md = render_claim_card(scored)
        assert "🟡" in md
        assert "不确定" in md

    def test_fallback_emoji_for_unknown_color(self):
        scored = ScoredClaimResult(
            claim_id="C004",
            claim_text="???",
            cited_paper="?",
            verdict="supported",
            confidence=0.5,
            color="blue",
            label="未知",
        )
        md = render_claim_card(scored)
        assert "⚪" in md


class TestRenderFactcheckMarkdown:
    def test_full_report_structure(self):
        scored = [
            ScoredClaimResult("C001", "Good claim", "Paper A", "supported", 0.9, "green", "正确", "ok"),
            ScoredClaimResult("C002", "Bad claim", "Paper B", "contradicted", 0.85, "red", "错误", "wrong"),
        ]
        result = FactCheckResult(
            quest_id="Q1",
            source_pdf="test.pdf",
            total_claims=2,
            green_count=1,
            yellow_count=0,
            red_count=1,
            results=scored,
        )
        md = render_factcheck_markdown(result)
        assert "FactCheck Report" in md
        assert "test.pdf" in md
        assert "Q1" in md
        assert "FAIL" in md
        assert "Good claim" in md
        assert "Bad claim" in md
        assert "Paper A" in md
        assert "Paper B" in md

    def test_empty_report(self):
        result = FactCheckResult(
            quest_id="Q1",
            source_pdf="empty.pdf",
            total_claims=0,
            green_count=0,
            yellow_count=0,
            red_count=0,
        )
        md = render_factcheck_markdown(result)
        assert "no claims" in md.lower()
        assert "N/A" in md


class TestRenderFactcheckSummary:
    def test_mixed_summary(self):
        scored = [
            ScoredClaimResult("C001", "A", "X", "supported", 0.9, "green", "正确"),
            ScoredClaimResult("C002", "B", "Y", "contradicted", 0.8, "red", "错误"),
            ScoredClaimResult("C003", "C", "Z", "uncertain", 0.5, "yellow", "不确定"),
        ]
        result = FactCheckResult("Q1", "t.pdf", 3, 1, 1, 1, results=scored)
        summary = render_factcheck_summary(result)
        assert "FAIL" in summary
        assert "🟢" in summary
        assert "🟡" in summary
        assert "🔴" in summary

    def test_empty_summary(self):
        result = FactCheckResult("Q1", "t.pdf", 0, 0, 0, 0)
        assert "no claims" in render_factcheck_summary(result).lower()
