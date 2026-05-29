from __future__ import annotations

import re
from pathlib import Path

from . import Claim

MAX_EXTRACTED_CHARS = 200_000
MAX_RETURNED_CLAIMS = 40
MIN_READABLE_RATIO = 0.45

_CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_PDF_OPERATOR_PATTERN = re.compile(r"\b(?:BT|ET|Tf|Tm|Td|Tj|TJ|rg|RG|cm|q|Q|Do|re|m|l|S|f|B)\b")
_CITATION_BLOCK_PATTERN = re.compile(r"\[([^\[\]]+)\]")
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[\.\!\?。！？])(?:\s+|\n+)")
_ABBREV_PATTERN = re.compile(r"\b(?:et al|i\.e|e\.g|vs|fig|Fig|Eq|eq|Dr|Prof|Mr|Ms)\.", flags=re.IGNORECASE)
_DECIMAL_PATTERN = re.compile(r"(\d+)\.(\d+)")
_REFERENCE_HEADING_PATTERN = re.compile(
    r"\b(?:REFERENCES|BIBLIOGRAPHY|参考文献)\b\s*\[",
    flags=re.IGNORECASE,
)


class PDFExtractionError(ValueError):
    """Raised when PDF text extraction produces unreadable content."""


def _clean_extracted_text(text: str) -> str:
    text = _CONTROL_CHARS_PATTERN.sub(" ", text)
    text = _PDF_OPERATOR_PATTERN.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_EXTRACTED_CHARS:
        text = text[:MAX_EXTRACTED_CHARS]
    return text


def _readability_ratio(text: str) -> float:
    if not text:
        return 0.0
    readable = sum(ch.isalnum() or ch.isspace() or ch in ".,;:!?-_/()[]'\"" for ch in text)
    return readable / max(1, len(text))


def _validate_readability(text: str) -> None:
    if not text:
        raise PDFExtractionError("PDF text extraction failed")
    if _readability_ratio(text) < MIN_READABLE_RATIO:
        raise PDFExtractionError("PDF text extraction failed")


def _read_pdf_like_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8")
    if suffix != ".pdf":
        return path.read_text(encoding="utf-8")

    # Use PyPDF2 for proper PDF text extraction (installed in venv)
    try:
        from PyPDF2 import PdfReader

        reader = PdfReader(str(path))
        pages: list[str] = []
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(text)
        if pages:
            cleaned = _clean_extracted_text("\n".join(pages))
            _validate_readability(cleaned)
            return cleaned
    except Exception:
        pass

    # Fallback: lightweight byte-decode for malformed PDFs
    raw = path.read_bytes()
    text = raw.decode("latin-1", errors="ignore")
    lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if any(token in line for token in ("obj", "endobj", "stream", "endstream", "/Type", "/Length")):
            continue
        cleaned = re.sub(r"[^A-Za-z0-9\[\]\(\)\-_,.;:!?/\s]", " ", line).strip()
        if len(cleaned) >= 20:
            lines.append(cleaned)

    cleaned = _clean_extracted_text("\n".join(lines))
    _validate_readability(cleaned)
    return cleaned


def _split_main_and_references(text: str) -> tuple[str, str]:
    match = _REFERENCE_HEADING_PATTERN.search(text)
    if not match:
        return text, ""
    # The pattern matches up to and including the '[' after REFERENCES,
    # e.g. "...REFERENCES [".  Back up to just before that '[' so the
    # references text starts with "[1] ...".
    bracket_pos = text.find("[", match.start())
    if bracket_pos == -1:
        return text, ""
    return text[:bracket_pos].strip(), text[bracket_pos:].strip()


def _parse_reference_index(reference_text: str) -> dict[str, str]:
    """Build a mapping from citation markers to paper titles.

    Splits the references text on every occurrence of ``[N]`` (including when
    PDF extraction has collapsed multiple entries onto one line).  Extracts
    the quoted paper title; falls back to the first sentence of the entry.
    """
    # ------------------------------------------------------------------
    # 1. Split into per-entry blocks by finding every [N] or [Name]
    # ------------------------------------------------------------------
    # Try numeric markers first (IEEE style: [1], [19]); fall back to
    # named markers ([Smith et al. 2023]) for non-standard formats.
    _DIGIT_MARKER = re.compile(r"\[(\d+(?:[–,\-\s]+\d+)*)\]\s*")
    _NAMED_MARKER = re.compile(r"\[([^\]]+)\]\s*")

    blocks: list[tuple[str, str]] = []  # (marker, body)

    digit_matches = list(_DIGIT_MARKER.finditer(reference_text))
    if digit_matches:
        entry_pattern = _DIGIT_MARKER
        matches = digit_matches
    else:
        entry_pattern = _NAMED_MARKER
        matches = list(_NAMED_MARKER.finditer(reference_text))

    for m in matches:
        marker = m.group(1).strip()
        start = m.end()
        # Body runs until the next entry marker or end of text
        next_match = entry_pattern.search(reference_text, start)
        body = reference_text[start:next_match.start()] if next_match else reference_text[start:]
        blocks.append((marker, body.strip()))

    # ------------------------------------------------------------------
    # 2. For each block, extract the paper title (prefer quoted title)
    # ------------------------------------------------------------------
    marker_to_title: dict[str, str] = {}
    _QUOTED_TITLE = re.compile(r"[\"“”„‘’「」『』]([^\"“”„‘’「」『』]+)[\"“”„‘’「」『』]")
    _SENTENCE = re.compile(r"([^\.]+\.)")

    for marker, body in blocks:
        if not body:
            continue
        # Strategy A: pull the first quoted string (the paper title)
        qt = _QUOTED_TITLE.search(body)
        if qt:
            marker_to_title[marker] = qt.group(1).strip()
            continue
        # Strategy B: use the first sentence as a fallback label
        st = _SENTENCE.search(body)
        if st:
            marker_to_title[marker] = st.group(1).strip()
            continue
        # Strategy C: raw first 120 chars
        marker_to_title[marker] = body[:120].strip()

    return marker_to_title


def _split_sentences(text: str) -> list[str]:
    protected = _DECIMAL_PATTERN.sub(r"\1__DOT__\2", text)
    protected = _ABBREV_PATTERN.sub(lambda m: m.group(0).replace(".", "__DOT__"), protected)
    parts = _SENTENCE_SPLIT_PATTERN.split(protected)
    restored = [part.replace("__DOT__", ".").strip() for part in parts]
    return [part for part in restored if part]


def _looks_like_claim(sentence: str) -> bool:
    s = sentence.strip()
    if len(s) < 20:
        return False
    if not _CITATION_BLOCK_PATTERN.search(s):
        return False
    keywords = (
        "improve",
        "improves",
        "increase",
        "increases",
        "decrease",
        "decreases",
        "outperform",
        "outperforms",
        "achieve",
        "achieves",
        "significant",
        "显著",
        "提升",
        "降低",
        "达到",
    )
    has_number = any(ch.isdigit() for ch in s)
    has_keyword = any(k in s.lower() for k in keywords)
    return has_number or has_keyword


def parse_pdf(pdf_path: str) -> list[Claim]:
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {pdf_path}")

    text = _read_pdf_like_text(path)
    main_text, references = _split_main_and_references(text)
    marker_to_title = _parse_reference_index(references)

    claims: list[Claim] = []
    claim_index = 1
    for sentence in _split_sentences(main_text):
        if len(claims) >= MAX_RETURNED_CLAIMS:
            break
        sentence = sentence.strip()
        if not sentence or not _looks_like_claim(sentence):
            continue

        markers: list[str] = []
        for match in _CITATION_BLOCK_PATTERN.finditer(sentence):
            block = match.group(1)
            for token in re.split(r"[;,，；]", block):
                marker = token.strip()
                if marker:
                    markers.append(f"[{marker}]")

        if not markers:
            continue

        resolved_title = ""
        for marker in markers:
            key = marker[1:-1].strip()
            if key in marker_to_title:
                resolved_title = marker_to_title[key]
                break

        claims.append(
            Claim(
                claim_id=f"C{claim_index:03d}",
                claim_text=sentence,
                citation_markers=markers,
                cited_paper_title=resolved_title,
            )
        )
        claim_index += 1

    return claims
