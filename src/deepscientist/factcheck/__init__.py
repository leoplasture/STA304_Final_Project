from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Claim:
    """A single factual claim extracted from a report or paper text."""

    claim_id: str
    claim_text: str
    citation_markers: list[str]
    cited_paper_title: str


@dataclass
class VerificationResult:
    """Verification result for one claim against one cited paper."""

    claim_id: str
    claim_text: str
    cited_paper: str
    verdict: str
    evidence_level: str
    evidence_snippet: str
    confidence: float
    notes: str = ""

