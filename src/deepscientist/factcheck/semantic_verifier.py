from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import parse as urlparse
from urllib import request as urlrequest

from . import VerificationResult

_DEFAULT_TIMEOUT_SECONDS = 15
_SEMANTIC_SCHOLAR_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
_CROSSREF_WORKS = "https://api.crossref.org/works"
_ARXIV_API = "https://export.arxiv.org/api/query"


@dataclass
class _PaperEvidence:
    cited_paper: str
    evidence_level: str
    text: str
    snippet: str


def _http_get_json(url: str, *, timeout: int = _DEFAULT_TIMEOUT_SECONDS, headers: dict[str, str] | None = None) -> dict[str, Any]:
    req = urlrequest.Request(url, headers=headers or {})
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
    obj = json.loads(payload)
    if not isinstance(obj, dict):
        return {}
    return obj


def _http_get_text(url: str, *, timeout: int = _DEFAULT_TIMEOUT_SECONDS, headers: dict[str, str] | None = None) -> str:
    req = urlrequest.Request(url, headers=headers or {})
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _search_semantic_scholar(title: str, *, timeout: int) -> tuple[str, str]:
    params = urlparse.urlencode({"query": title, "limit": 1, "fields": "title,abstract,externalIds,url"})
    url = f"{_SEMANTIC_SCHOLAR_SEARCH}?{params}"
    headers = {}
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    data = _http_get_json(url, timeout=timeout, headers=headers)
    rows = data.get("data")
    if not isinstance(rows, list) or not rows:
        return "", ""
    row = rows[0] if isinstance(rows[0], dict) else {}
    return str(row.get("title") or ""), str(row.get("abstract") or "")


def _search_crossref_title(title: str, *, timeout: int) -> str:
    params = urlparse.urlencode({"query.title": title, "rows": 1})
    data = _http_get_json(f"{_CROSSREF_WORKS}?{params}", timeout=timeout)
    items = ((data.get("message") or {}).get("items") or []) if isinstance(data.get("message"), dict) else []
    if not isinstance(items, list) or not items:
        return ""
    item = items[0] if isinstance(items[0], dict) else {}
    titles = item.get("title") or []
    if isinstance(titles, list) and titles:
        return str(titles[0] or "")
    return ""


def _search_arxiv_abstract(title: str, *, timeout: int) -> tuple[str, str]:
    params = urlparse.urlencode({"search_query": f"all:{title}", "start": 0, "max_results": 1})
    xml = _http_get_text(f"{_ARXIV_API}?{params}", timeout=timeout)
    title_match = re.search(r"<title>(.*?)</title>", xml, flags=re.DOTALL)
    summary_match = re.search(r"<summary>(.*?)</summary>", xml, flags=re.DOTALL)
    found_title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
    found_summary = re.sub(r"\s+", " ", summary_match.group(1)).strip() if summary_match else ""
    return found_title, found_summary


def _best_evidence_for_title(cited_paper_title: str, *, timeout: int, fallback_query: str = "") -> _PaperEvidence:
    """Search for paper evidence by title.  If the title is empty, falls back to
    searching by *fallback_query* (e.g. the claim text) so that verification can
    still proceed when the PDF parser cannot resolve numeric citation markers."""
    cited = cited_paper_title.strip()

    # --- first try the explicit paper title ---------------------------------
    if cited:
        try:
            title, abstract = _search_semantic_scholar(cited, timeout=timeout)
            if abstract.strip():
                snippet = abstract.split(".")[0].strip()
                return _PaperEvidence(cited_paper=title or cited, evidence_level="abstract_only", text=abstract, snippet=snippet)
        except Exception:
            pass

        try:
            title, summary = _search_arxiv_abstract(cited, timeout=timeout)
            if summary.strip():
                snippet = summary.split(".")[0].strip()
                return _PaperEvidence(cited_paper=title or cited, evidence_level="abstract_only", text=summary, snippet=snippet)
        except Exception:
            pass

        try:
            title = _search_crossref_title(cited, timeout=timeout)
            if title.strip():
                return _PaperEvidence(
                    cited_paper=title,
                    evidence_level="abstract_only",
                    text=title,
                    snippet=title,
                )
        except Exception:
            pass

        return _PaperEvidence(cited_paper=cited, evidence_level="abstract_only", text="", snippet="")

    # --- fallback: search by claim keywords ---------------------------------
    if fallback_query.strip():
        query = _build_search_query(fallback_query)
        if query:
            try:
                title, abstract = _search_semantic_scholar(query, timeout=timeout)
                if title.strip():
                    snippet = abstract.split(".")[0].strip() if abstract.strip() else ""
                    return _PaperEvidence(
                        cited_paper=title,
                        evidence_level="abstract_only",
                        text=abstract,
                        snippet=snippet,
                    )
            except Exception:
                pass

    return _PaperEvidence(cited_paper="", evidence_level="abstract_only", text="", snippet="")


def _tokenize(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-z0-9]+", text.lower()) if len(tok) >= 3}


def _build_search_query(claim_text: str) -> str:
    """Build a short keyword query from claim text for paper-title search.

    Strips citation markers and parenthetical expansions, then keeps only the
    first 4-6 meaningful words — enough for Semantic Scholar title search."""
    cleaned = re.sub(r"\[[\d,\-\s]+\]", "", claim_text)
    # Remove parenthetical expansions like "(FL)", "(MHPFL)"
    cleaned = re.sub(r"\([A-Z]{2,}\)", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Take first meaningful segment, keeping it short for title-matching
    words = cleaned.split()
    # Keep 4-7 words as a concise search phrase
    return " ".join(words[:7]) if len(words) > 7 else cleaned


def _heuristic_verdict(claim_text: str, evidence_text: str) -> tuple[str, float, str]:
    claim_tokens = _tokenize(claim_text)
    evidence_tokens = _tokenize(evidence_text)
    if not evidence_tokens:
        return "not_found", 0.0, ""

    overlap = claim_tokens & evidence_tokens
    overlap_ratio = len(overlap) / max(len(claim_tokens), 1)
    neg_markers = {"not", "never", "no", "without", "fail", "fails", "failed"}
    claim_has_neg = bool(claim_tokens & neg_markers)
    evidence_has_neg = bool(evidence_tokens & neg_markers)

    if overlap_ratio < 0.15:
        return "uncertain", 0.45, ""
    if claim_has_neg ^ evidence_has_neg:
        return "contradicted", min(0.9, 0.55 + overlap_ratio), ""
    return "supported", min(0.95, 0.6 + overlap_ratio), ""


def verify_claim(claim_text: str, cited_paper_title: str) -> VerificationResult:
    timeout = int(os.getenv("FACTCHECK_HTTP_TIMEOUT_SECONDS", str(_DEFAULT_TIMEOUT_SECONDS)))
    evidence = _best_evidence_for_title(
        cited_paper_title,
        timeout=timeout,
        fallback_query=claim_text if not cited_paper_title.strip() else "",
    )
    if not evidence.text.strip():
        return VerificationResult(
            claim_id="",
            claim_text=claim_text,
            cited_paper=evidence.cited_paper or cited_paper_title or "(searched by claim text — no matching paper found)",
            verdict="not_found",
            evidence_level="abstract_only",
            evidence_snippet="",
            confidence=0.0,
            notes="No abstract/full text found from providers." + (
                " Citation markers could not be resolved to paper titles." if not cited_paper_title.strip() else ""
            ),
        )

    verdict, confidence, _ = _heuristic_verdict(claim_text, evidence.text)
    notes = ""
    if verdict == "uncertain":
        notes = "Evidence has partial lexical overlap but is insufficient for a strong conclusion."
    elif verdict == "contradicted":
        notes = "Detected polarity mismatch between claim and evidence text."

    return VerificationResult(
        claim_id="",
        claim_text=claim_text,
        cited_paper=evidence.cited_paper or cited_paper_title,
        verdict=verdict,
        evidence_level=evidence.evidence_level,
        evidence_snippet=evidence.snippet,
        confidence=round(confidence, 3),
        notes=notes,
    )

