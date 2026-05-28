from __future__ import annotations

import re
from pathlib import Path

from . import Claim

_CITATION_BLOCK_PATTERN = re.compile(r"\[([^\[\]]+)\]")
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[\.\!\?。！？])(?:\s+|\n+)")
_ABBREV_PATTERN = re.compile(r"\b(?:et al|i\.e|e\.g|vs|fig|Fig|Eq|eq|Dr|Prof|Mr|Ms)\.", flags=re.IGNORECASE)
_DECIMAL_PATTERN = re.compile(r"(\d+)\.(\d+)")
_REFERENCE_HEADING_PATTERN = re.compile(
    r"^(references|bibliography|参考文献)\s*$",
    flags=re.IGNORECASE | re.MULTILINE,
)


def _read_pdf_like_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8")
    if suffix != ".pdf":
        return path.read_text(encoding="utf-8")

    raw = path.read_bytes()
    # Lightweight fallback parser: decode printable chunks from PDF bytes.
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
    return "\n".join(lines)


def _split_main_and_references(text: str) -> tuple[str, str]:
    match = _REFERENCE_HEADING_PATTERN.search(text)
    if not match:
        return text, ""
    return text[: match.start()].strip(), text[match.end() :].strip()


def _parse_reference_index(reference_text: str) -> dict[str, str]:
    marker_to_title: dict[str, str] = {}
    if not reference_text:
        return marker_to_title

    # Supports lines like:
    # [1] Paper Title...
    # [Smith et al. 2023] Paper Title...
    for raw_line in reference_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^\[([^\]]+)\]\s*(.+)$", line)
        if not match:
            continue
        marker = match.group(1).strip()
        title = match.group(2).strip()
        if marker and title:
            marker_to_title[marker] = title
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
