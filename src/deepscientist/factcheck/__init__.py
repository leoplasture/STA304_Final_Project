"""FactCheck: literature citation verification for DeepScientist.

Shared dataclasses used by Persons A, B, and C.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Claim:
    """A single factual claim extracted from a research report or hypothesis."""

    claim_id: str                # "C001"
    claim_text: str              # "Attention improves BLEU by 2.4 points"
    citation_markers: list[str]  # ["[Smith et al. 2023]", "[Chen 2024]"]
    cited_paper_title: str       # resolved paper title (or "" if unresolved)


@dataclass
class VerificationResult:
    """Result of checking one claim against its cited source."""

    claim_id: str                # matches Claim.claim_id
    claim_text: str
    cited_paper: str             # "Smith et al. (2023)"
    verdict: str                 # "supported" | "contradicted" | "not_found" | "uncertain"
    evidence_level: str          # "full_text" | "abstract_only"
    evidence_snippet: str        # the sentence from source that supports/contradicts
    confidence: float            # 0.0 - 1.0
    notes: str = ""              # e.g. "abstract mentions BLEU but not the 2.4 value"


@dataclass
class ScoredClaimResult:
    """Verification result plus traffic-light label for rendering."""

    claim_id: str
    claim_text: str
    cited_paper: str
    verdict: str                 # "supported" | "contradicted" | "not_found" | "uncertain"
    confidence: float            # 0.0 - 1.0
    color: str                   # "green" | "yellow" | "red"
    label: str                   # "正确" | "不确定" | "错误"
    rationale: str = ""


@dataclass
class FactCheckResult:
    """Aggregated fact-check result for a batch of claims."""

    quest_id: str
    source_pdf: str              # path to the source PDF
    total_claims: int
    green_count: int
    yellow_count: int
    red_count: int
    results: list[ScoredClaimResult] = field(default_factory=list)

    @property
    def score(self) -> str:
        if self.total_claims == 0:
            return "N/A"
        if self.red_count > 0:
            return "FAIL"
        if self.yellow_count > self.total_claims * 0.3:
            return "WARN"
        return "PASS"
