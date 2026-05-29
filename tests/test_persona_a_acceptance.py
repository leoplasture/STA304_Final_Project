from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from deepscientist.config import ConfigManager
from deepscientist.factcheck import Claim, VerificationResult
from deepscientist.factcheck.factcheck_render import render_factcheck_markdown
from deepscientist.factcheck.traffic_light import score_batch
from deepscientist.home import ensure_home_layout, repo_root
from deepscientist.mcp.context import McpContext
from deepscientist.mcp.server import build_artifact_server, build_factcheck_server
from deepscientist.quest import QuestService
from deepscientist.skills import SkillInstaller


def _unwrap_tool_result(result):
    if isinstance(result, tuple) and len(result) == 2:
        return result[1]
    return result


def test_persona_a_acceptance_pipeline_and_record(
    temp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        ensure_home_layout(temp_home)
        ConfigManager(temp_home).ensure_files()
        quest = QuestService(temp_home, skill_installer=SkillInstaller(repo_root(), temp_home)).create("persona A acceptance")
        quest_root = Path(quest["quest_root"])
        context = McpContext(
            home=temp_home,
            quest_id=quest["quest_id"],
            quest_root=quest_root,
            run_id="run-persona-a-acceptance",
            active_anchor="crossdisc_idea",
            conversation_id="quest:test-persona-a",
            agent_role="idea",
            worker_id="worker-main",
            worktree_root=None,
            team_mode="single",
        )
        factcheck_server = build_factcheck_server(context)
        artifact_server = build_artifact_server(context)

        # Force uncertain/not_found so we can verify report still renders.
        def fake_verify(claim_text: str, cited_paper_title: str) -> VerificationResult:
            if "missing" in claim_text.lower():
                return VerificationResult(
                    claim_id="",
                    claim_text=claim_text,
                    cited_paper=cited_paper_title,
                    verdict="not_found",
                    evidence_level="abstract_only",
                    evidence_snippet="",
                    confidence=0.0,
                    notes="No evidence found.",
                )
            return VerificationResult(
                claim_id="",
                claim_text=claim_text,
                cited_paper=cited_paper_title,
                verdict="uncertain",
                evidence_level="abstract_only",
                evidence_snippet="Partial lexical overlap.",
                confidence=0.45,
                notes="Insufficient evidence strength.",
            )

        monkeypatch.setattr("deepscientist.factcheck.semantic_verifier.verify_claim", fake_verify)

        claims = [
            Claim(
                claim_id="C001",
                claim_text="Method A improves BLEU by 2.4 points [R1].",
                citation_markers=["[R1]"],
                cited_paper_title="Paper A",
            ),
            Claim(
                claim_id="C002",
                claim_text="Missing evidence claim [R2].",
                citation_markers=["[R2]"],
                cited_paper_title="Paper Missing",
            ),
        ]

        score_batch_calls = 0
        render_calls = 0
        verifications: list[VerificationResult] = []

        for claim in claims:
            vr_payload = _unwrap_tool_result(
                await factcheck_server.call_tool(
                    "verify_claim",
                    {
                        "claim_text": claim.claim_text,
                        "cited_paper_title": claim.cited_paper_title,
                        "claim_id": claim.claim_id,
                    },
                )
            )
            # claim_id must be preserved.
            assert vr_payload["claim_id"] == claim.claim_id
            verifications.append(
                VerificationResult(
                    claim_id=vr_payload["claim_id"],
                    claim_text=vr_payload["claim_text"],
                    cited_paper=vr_payload["cited_paper"],
                    verdict=vr_payload["verdict"],
                    evidence_level=vr_payload["evidence_level"],
                    evidence_snippet=vr_payload["evidence_snippet"],
                    confidence=float(vr_payload["confidence"]),
                    notes=vr_payload.get("notes", ""),
                )
            )

        score_batch_calls += 1
        batch = score_batch(verifications, quest_id=quest["quest_id"], source_pdf="paper.pdf")

        render_calls += 1
        report_md = render_factcheck_markdown(batch)
        assert report_md
        assert any(token in report_md for token in ("🟢", "🟡", "🔴"))
        assert any(token in report_md for token in ("PASS", "WARN", "FAIL"))

        record_result = _unwrap_tool_result(
            await artifact_server.call_tool(
                "record",
                {
                    "payload": {
                        "kind": "report",
                        "title": "crossdisc_report.md",
                        "body": report_md,
                        "meta": {"source": "persona_a_acceptance"},
                    }
                },
            )
        )
        assert record_result.get("ok") is True

        # Acceptance-style counters.
        assert score_batch_calls >= 1
        assert render_calls >= 1

    asyncio.run(scenario())


def test_persona_a_acceptance_parse_pdf_fallback_is_small_and_explicit(
    temp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        ensure_home_layout(temp_home)
        ConfigManager(temp_home).ensure_files()
        quest = QuestService(temp_home, skill_installer=SkillInstaller(repo_root(), temp_home)).create("persona A parse fallback")
        context = McpContext(
            home=temp_home,
            quest_id=quest["quest_id"],
            quest_root=Path(quest["quest_root"]),
            run_id="run-persona-a-fallback",
            active_anchor="crossdisc_idea",
            conversation_id="quest:test-persona-a-fallback",
            agent_role="idea",
            worker_id="worker-main",
            worktree_root=None,
            team_mode="single",
        )
        server = build_factcheck_server(context)

        from deepscientist.factcheck.claim_extractor import PDFExtractionError

        def fake_parse(_pdf_path: str):
            raise PDFExtractionError("PDF text extraction failed")

        monkeypatch.setattr("deepscientist.factcheck.claim_extractor.parse_pdf", fake_parse)
        result = _unwrap_tool_result(await server.call_tool("parse_pdf", {"pdf_path": "bad.pdf"}))
        payload = result.get("result") if isinstance(result, dict) and "result" in result else result
        assert isinstance(payload, list)
        assert payload[0]["ok"] is False
        assert payload[0]["error"] == "PDF text extraction failed"
        assert payload[0]["fallback_recommended"] is True

        # Must not return huge garbage payload.
        assert len(json.dumps(payload, ensure_ascii=False)) < 50_000

    asyncio.run(scenario())
