"""RYG Colored Markdown rendering for fact-check results.

Produces user-visible colored reports suitable for QQ Bot output.
Extends the rendering pattern from evidence_audit.py.
"""

from . import FactCheckResult, ScoredClaimResult

_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴"}

_COLOR_CSS = {
    "green": "color:#22863a; font-weight:bold;",
    "yellow": "color:#b08800; font-weight:bold;",
    "red": "color:#cb2431; font-weight:bold;",
}


def _html_span(color: str, text: str) -> str:
    style = _COLOR_CSS.get(color, "")
    return f'<span style="{style}">{text}</span>'


def render_claim_card(scored: ScoredClaimResult, *, index: int = 0) -> str:
    """Render a single claim with its RYG verdict as a Markdown card."""
    emoji = _EMOJI.get(scored.color, "⚪")
    lines = [
        f"### {emoji} Claim {scored.claim_id or f'#{index + 1}'} — {scored.label}",
        "",
        f"**Claim**: {scored.claim_text}",
        f"**Cited**: {scored.cited_paper}",
        f"**Verdict**: `{scored.verdict}` (confidence: {scored.confidence:.2f})",
        f"**Reason**: {scored.rationale}",
        "",
    ]
    return "\n".join(lines)


def render_factcheck_markdown(result: FactCheckResult) -> str:
    """Render a full FactCheckResult as a colored Markdown report."""
    lines = [
        "## 📋 FactCheck Report",
        "",
        f"**Source**: `{result.source_pdf}`",
        f"**Quest**: `{result.quest_id}`",
        "",
        "### Summary",
        "",
        f"| 🟢 正确 (Green) | 🟡 不确定 (Yellow) | 🔴 错误 (Red) | Total | Score |",
        f"|-----------------|---------------------|----------------|-------|-------|",
        f"| {result.green_count} | {result.yellow_count} | {result.red_count} | {result.total_claims} | **{result.score}** |",
        "",
    ]

    if result.total_claims == 0:
        lines.append("*(No claims to verify — the source may not contain any citable claims.)*")
        return "\n".join(lines)

    lines.append("### Per-Claim Details")
    lines.append("")

    for i, scored in enumerate(result.results):
        emoji = _EMOJI.get(scored.color, "⚪")
        status_badge = f"{emoji} **{scored.label}**"
        verdict_note = (
            f" (evidence: {scored.verdict}, confidence: {scored.confidence:.2f})"
        )
        lines.append(f"#### {i + 1}. {status_badge}{verdict_note}")
        lines.append("")
        lines.append(f"> {scored.claim_text}")
        lines.append("")
        if scored.cited_paper:
            lines.append(f"Cited source: *{scored.cited_paper}*")
        else:
            lines.append("Cited source: *(unresolved)*")
        lines.append("")
        if scored.rationale:
            lines.append(f"{scored.rationale}")
            lines.append("")

    return "\n".join(lines)


def render_factcheck_summary(result: FactCheckResult) -> str:
    """Compact one-line summary suitable for inline status updates."""
    if result.total_claims == 0:
        return "FactCheck: no claims found."
    parts = []
    if result.green_count:
        parts.append(f"{_EMOJI['green']} {result.green_count} correct")
    if result.yellow_count:
        parts.append(f"{_EMOJI['yellow']} {result.yellow_count} uncertain")
    if result.red_count:
        parts.append(f"{_EMOJI['red']} {result.red_count} wrong")
    return f"FactCheck [{result.score}]: " + ", ".join(parts)
