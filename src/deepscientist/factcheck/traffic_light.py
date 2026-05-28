"""Traffic-light scoring for fact-check verification results.

Maps (verdict, confidence) → RYG color per the Project A spec.
All verdict × confidence combinations are covered — no fallthrough.
"""

from . import FactCheckResult, ScoredClaimResult, VerificationResult


def score_verification(vr: VerificationResult) -> ScoredClaimResult:
    """Score a single VerificationResult into a ScoredClaimResult."""
    verdict = vr.verdict
    confidence = vr.confidence

    if verdict == "supported":
        if confidence >= 0.8:
            return ScoredClaimResult(
                claim_id=vr.claim_id,
                claim_text=vr.claim_text,
                cited_paper=vr.cited_paper,
                verdict=verdict,
                confidence=confidence,
                color="green",
                label="正确",
                rationale=f"原文明确支撑 (confidence={confidence:.2f})",
            )
        else:
            return ScoredClaimResult(
                claim_id=vr.claim_id,
                claim_text=vr.claim_text,
                cited_paper=vr.cited_paper,
                verdict=verdict,
                confidence=confidence,
                color="yellow",
                label="不确定",
                rationale=f"有支撑但置信度不足 (confidence={confidence:.2f})",
            )

    if verdict == "contradicted":
        if confidence >= 0.7:
            return ScoredClaimResult(
                claim_id=vr.claim_id,
                claim_text=vr.claim_text,
                cited_paper=vr.cited_paper,
                verdict=verdict,
                confidence=confidence,
                color="red",
                label="错误",
                rationale=f"原文明确反驳 (confidence={confidence:.2f})",
            )
        else:
            return ScoredClaimResult(
                claim_id=vr.claim_id,
                claim_text=vr.claim_text,
                cited_paper=vr.cited_paper,
                verdict=verdict,
                confidence=confidence,
                color="yellow",
                label="不确定",
                rationale=f"存在反驳信号但置信度不足 (confidence={confidence:.2f})",
            )

    if verdict in ("uncertain", "not_found"):
        return ScoredClaimResult(
            claim_id=vr.claim_id,
            claim_text=vr.claim_text,
            cited_paper=vr.cited_paper,
            verdict=verdict,
            confidence=confidence,
            color="yellow",
            label="不确定",
            rationale=f"无法确认 ({'原文未找到相关证据' if verdict == 'not_found' else '语义验证结果不确定'})",
        )

    # Defensive: any unknown verdict
    return ScoredClaimResult(
        claim_id=vr.claim_id,
        claim_text=vr.claim_text,
        cited_paper=vr.cited_paper,
        verdict=verdict,
        confidence=confidence,
        color="yellow",
        label="不确定",
        rationale=f"未知判定类型 (verdict={verdict})",
    )


def score_batch(
    results: list[VerificationResult],
    *,
    quest_id: str = "",
    source_pdf: str = "",
) -> FactCheckResult:
    """Score a batch of VerificationResults into an aggregated FactCheckResult.

    claim_id mapping: since verify_claim doesn't receive claim_id, B maps it
    externally.  This function copies the claim_id from each VerificationResult
    as-is; pre-populate it before calling if needed.
    """
    scored: list[ScoredClaimResult] = [score_verification(vr) for vr in results]
    green = sum(1 for s in scored if s.color == "green")
    yellow = sum(1 for s in scored if s.color == "yellow")
    red = sum(1 for s in scored if s.color == "red")

    return FactCheckResult(
        quest_id=quest_id,
        source_pdf=source_pdf,
        total_claims=len(scored),
        green_count=green,
        yellow_count=yellow,
        red_count=red,
        results=scored,
    )
