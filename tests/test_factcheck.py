from __future__ import annotations

import json
from pathlib import Path

from deepscientist.factcheck.claim_extractor import parse_pdf
from deepscientist.factcheck.semantic_verifier import verify_claim


def test_parse_pdf_extracts_claims_from_text_file(tmp_path: Path) -> None:
    content = (
        "Model A improves BLEU by 2.4 points over baseline [Smith et al. 2023].\n"
        "This sentence has no citation and should be ignored.\n\n"
        "References\n"
        "[Smith et al. 2023] Attention improves BLEU by 2.4 points in MT benchmarks.\n"
    )
    path = tmp_path / "sample.txt"
    path.write_text(content, encoding="utf-8")

    claims = parse_pdf(str(path))
    assert len(claims) == 1
    assert claims[0].claim_id == "C001"
    assert "[Smith et al. 2023]" in claims[0].citation_markers
    assert "Attention improves BLEU" in claims[0].cited_paper_title


def test_parse_pdf_unresolved_marker_keeps_empty_title(tmp_path: Path) -> None:
    content = (
        "Method B reduces latency by 30% [Unknown 2025].\n\n"
        "References\n"
        "[Other 2024] Not matched title.\n"
    )
    path = tmp_path / "sample2.txt"
    path.write_text(content, encoding="utf-8")
    claims = parse_pdf(str(path))
    assert len(claims) == 1
    assert claims[0].cited_paper_title == ""


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> bytes:
        return self._text.encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_verify_claim_supported(monkeypatch) -> None:
    payload = {"data": [{"title": "Paper X", "abstract": "This study shows model A improves BLEU by 2.4 points over baseline."}]}

    def fake_http_get_json(url, timeout=0, headers=None):  # noqa: ANN001
        _ = (url, timeout, headers)
        return payload

    monkeypatch.setattr("deepscientist.factcheck.semantic_verifier._http_get_json", fake_http_get_json)
    result = verify_claim("Model A improves BLEU by 2.4 points over baseline.", "Paper X")
    assert result.verdict == "supported"
    assert result.evidence_level == "abstract_only"
    assert result.confidence >= 0.6


def test_verify_claim_not_found(monkeypatch) -> None:
    def fake_http_get_json(url, timeout=0, headers=None):  # noqa: ANN001
        _ = (url, timeout, headers)
        return {"data": []}

    monkeypatch.setattr("deepscientist.factcheck.semantic_verifier._http_get_json", fake_http_get_json)
    result = verify_claim("A claim without evidence.", "Unknown paper")
    assert result.verdict == "not_found"
    assert result.confidence == 0.0
