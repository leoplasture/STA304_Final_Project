"""Tests for evidence_audit — report scanning and evidence quality checks."""

from __future__ import annotations

import json
from pathlib import Path

from deepscientist.evidence_audit import (
    AuditResult,
    audit_report,
    build_evidence_table,
    render_audit_markdown,
)
from deepscientist.evidence_chain import record_event


def _quest_root(tmp_path: Path) -> Path:
    root = tmp_path / "quest"
    (root / ".ds").mkdir(parents=True, exist_ok=True)
    return root


def _seed_evidence(quest_root: Path, run_id: str = "run-a") -> None:
    record_event(
        quest_root,
        run_id=run_id,
        event={
            "event_id": "evt-1",
            "type": "runner.tool_call",
            "tool_call_id": "call-1",
            "tool_name": "artifact.arxiv",
            "created_at": "2026-05-24T10:00:00+00:00",
        },
    )
    record_event(
        quest_root,
        run_id=run_id,
        event={
            "event_id": "evt-2",
            "type": "runner.tool_result",
            "tool_call_id": "call-1",
            "tool_name": "artifact.arxiv",
            "output": '{"title": "Attention Is All You Need", "summary": "Proposes the Transformer architecture."}',
        },
    )
    record_event(
        quest_root,
        run_id=run_id,
        event={
            "event_id": "evt-3",
            "type": "runner.tool_result",
            "tool_call_id": "call-2",
            "tool_name": "bash_exec.bash_exec",
            "output": "BLEU=28.4",
            "metadata": {"kind": "stdout", "path": "experiment/log.txt", "line": 45},
        },
    )
    record_event(
        quest_root,
        run_id=run_id,
        event={
            "event_id": "evt-4",
            "type": "runner.tool_result",
            "tool_call_id": "call-3",
            "tool_name": "web_search.search",
            "status": "failed",
            "error": "timeout",
        },
    )


# --- Core audit tests ---

def test_audit_all_valid_citations(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    _seed_evidence(quest_root)

    report = (
        "The Transformer architecture was proposed by Vaswani et al. [ev_run-a_000002]. "
        "On WMT14 En-De, it achieves BLEU 28.4 [ev_run-a_000003]. "
        "This suggests attention mechanisms can replace recurrence [推断]. "
        "Whether this extends to speech tasks is unknown [待验证]."
    )
    result = audit_report(report, quest_root)

    assert result.ok is True
    assert len(result.cited_ids) == 2
    assert result.supported_count == 2
    assert result.inferred_count == 1
    assert result.unverified_count == 1
    assert result.bare_sentence_count == 0
    assert not result.fake_ids


def test_audit_empty_store_reports_error(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    result = audit_report("Some claim about AI.", quest_root)
    assert result.ok is False
    assert any("empty" in err.lower() for err in result.errors)


def test_audit_fake_evidence_id_detected(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    _seed_evidence(quest_root)

    report = "The model uses a novel activation function [ev_run-a_999999]."
    result = audit_report(report, quest_root)

    assert "ev_run-a_999999" in result.fake_ids
    assert result.ok is False


def test_audit_bare_claims_detected(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    _seed_evidence(quest_root)

    report = (
        "The Transformer uses self-attention [ev_run-a_000002]. "
        "Self-attention is more parallelizable than RNNs. "
        "The model trains faster on GPU hardware. "
        "However it requires more memory for long sequences. "
        "This is a significant limitation in practice."
    )
    result = audit_report(report, quest_root)

    assert result.bare_sentence_count >= 3
    assert result.ok is False


def test_audit_unused_evidence_tracked(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    _seed_evidence(quest_root)

    report = "The model achieves BLEU 28.4 [ev_run-a_000003]."
    result = audit_report(report, quest_root)

    # ev_run-a_000001, ev_run-a_000002 should be unused
    # ev_run-a_000004 is error status so excluded from unused
    assert len(result.unused_ids) >= 1


def test_audit_reports_errors(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    _seed_evidence(quest_root)
    store_path = quest_root / ".ds" / "evidence" / "evidence_store.json"
    store = json.loads(store_path.read_text(encoding="utf-8"))
    # Corrupt the store
    store["entries"] = "not_a_list"
    store_path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")

    result = audit_report("Some report [ev_run-a_000001].", quest_root)
    assert result.ok is False
    assert result.errors


def test_audit_simple_evidence_id_format(tmp_path: Path) -> None:
    """E001 style IDs — even if not in store, should be detected as cited."""
    quest_root = _quest_root(tmp_path)
    _seed_evidence(quest_root)

    report = "The result is significant [E001-img]. Further analysis needed [E002]."
    result = audit_report(report, quest_root)

    # E001-img and E002 are cited but not in store (store uses ev_ format)
    assert "E001-img" in result.cited_ids or "E002" in result.cited_ids


def test_audit_failed_tool_not_in_unused(tmp_path: Path) -> None:
    """Evidence from failed tools should be excluded from unused list."""
    quest_root = _quest_root(tmp_path)
    _seed_evidence(quest_root)

    report = "The model achieves BLEU 28.4 [ev_run-a_000003]."
    result = audit_report(report, quest_root)

    # ev_run-a_000004 is a failed tool call — should NOT be in unused_ids
    assert "ev_run-a_000004" not in result.unused_ids


# --- Render tests ---

def test_render_audit_markdown_pass(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    _seed_evidence(quest_root)

    report = "The model achieves BLEU 28.4 [ev_run-a_000003]."
    result = audit_report(report, quest_root)
    md = render_audit_markdown(result, quest_root)

    assert "PASS" in md
    assert "Evidence Chain Audit" in md


def test_render_audit_markdown_warn(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    _seed_evidence(quest_root)

    report = "The model uses a novel method [ev_run-a_999999]. It is very effective."
    result = audit_report(report, quest_root)
    md = render_audit_markdown(result, quest_root)

    assert "WARN" in md
    assert "ev_run-a_999999" in md
    assert "Bare claims" in md


# --- Evidence table builder ---

def test_build_evidence_table(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    _seed_evidence(quest_root)

    report = "BLEU is 28.4 [ev_run-a_000003] and the paper is Attention Is All You Need [ev_run-a_000002]."
    table = build_evidence_table(report, quest_root)

    assert "ev_run-a_000002" in table
    assert "ev_run-a_000003" in table
    assert "artifact.arxiv" in table
    assert "bash_exec" in table


def test_build_evidence_table_empty_report(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    table = build_evidence_table("No evidence here.", quest_root)
    assert "No evidence IDs found" in table


def test_english_annotations_detected(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    _seed_evidence(quest_root)

    report = (
        "The Transformer achieves BLEU 28.4 on WMT14 [ev_run-a_000003]. "
        "This suggests attention scales better than recurrence [Inferred]. "
        "Whether this generalizes to all NLP tasks is unclear [Needs Verification]."
    )
    result = audit_report(report, quest_root)

    assert result.supported_count == 1
    assert result.inferred_count == 1
    assert result.unverified_count == 1
    assert result.bare_sentence_count == 0
    assert result.ok is True


def test_mixed_language_annotations_detected(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    _seed_evidence(quest_root)

    report = (
        "The model scores 28.4 BLEU [ev_run-a_000003]. "
        "This is likely due to better parallelization [推断]. "
        "Other tasks remain unexplored [Inferred]. "
        "More experiments are needed [待验证]."
    )
    result = audit_report(report, quest_root)

    assert result.supported_count == 1
    assert result.inferred_count == 2
    assert result.unverified_count == 1
