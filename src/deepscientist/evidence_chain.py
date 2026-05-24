from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .shared import ensure_dir, read_json, utc_now, write_json

EVIDENCE_SCHEMA_VERSION = "1.0"
_DEFAULT_SOURCE_PATH = ".ds/events.jsonl"
_OUTPUT_PREVIEW_LIMIT = 512
_OUTPUT_SIDECAR_THRESHOLD_BYTES = 4_000
_REQUIRED_ENTRY_FIELDS = (
    "schema_version",
    "evidence_id",
    "run_id",
    "event_id",
    "tool_call_id",
    "event_type",
    "tool_name",
    "created_at",
    "source_type",
    "source_ref",
    "args",
    "output_preview",
    "sidecar_path",
    "payload_sha256",
    "status",
    "error",
)


def _store_path(quest_root: Path) -> Path:
    return quest_root / ".ds" / "evidence" / "evidence_store.json"


def _sidecar_dir(quest_root: Path) -> Path:
    return quest_root / ".ds" / "evidence" / "sidecars"


def _payload_sha256(payload: Any) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        text = str(payload)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _json_or_raw(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return {"items": value}
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return {}
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return {"raw": value}
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
        return {"value": parsed}
    if value is None:
        return {}
    return {"value": value}


def _output_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(value)


def _output_preview(value: str) -> str:
    text = str(value or "").strip()
    if len(text) <= _OUTPUT_PREVIEW_LIMIT:
        return text
    return text[: _OUTPUT_PREVIEW_LIMIT - 1].rstrip() + "..."


def _source_ref_for_event(event: dict[str, Any], evidence_packet: dict[str, Any], *, sidecar_path: str | None) -> dict[str, Any]:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    source_path = str(metadata.get("path") or _DEFAULT_SOURCE_PATH)
    source_kind = "stdout"
    if evidence_packet.get("sidecar_path") or sidecar_path:
        source_kind = "sidecar"
        source_path = str(evidence_packet.get("sidecar_path") or sidecar_path or source_path)
    elif isinstance(metadata.get("url"), str) and str(metadata.get("url")).strip():
        source_kind = "url"
    elif str(metadata.get("kind") or "").strip().lower() in {"pdf", "web", "url", "sidecar", "stdout"}:
        source_kind = str(metadata.get("kind")).strip().lower()
    page_value = metadata.get("page")
    line_value = metadata.get("line")
    try:
        page = int(page_value) if page_value is not None else None
    except Exception:
        page = None
    try:
        line = int(line_value) if line_value is not None else None
    except Exception:
        line = None
    return {
        "kind": source_kind,
        "path": source_path,
        "line": line,
        "url": str(metadata.get("url")).strip() if isinstance(metadata.get("url"), str) and str(metadata.get("url")).strip() else None,
        "page": page,
        "sidecar_path": str(evidence_packet.get("sidecar_path") or sidecar_path or "").strip() or None,
        "event_id": str(event.get("event_id") or "").strip() or None,
        "tool_call_id": str(event.get("tool_call_id") or "").strip() or None,
    }


def _hash_material_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": str(entry.get("schema_version") or EVIDENCE_SCHEMA_VERSION),
        "run_id": str(entry.get("run_id") or ""),
        "event_id": str(entry.get("event_id") or ""),
        "tool_call_id": str(entry.get("tool_call_id") or ""),
        "event_type": str(entry.get("event_type") or ""),
        "tool_name": str(entry.get("tool_name") or ""),
        "created_at": str(entry.get("created_at") or ""),
        "source_type": str(entry.get("source_type") or ""),
        "source_ref": dict(entry.get("source_ref") or {}),
        "args": dict(entry.get("args") or {}),
        "output_preview": str(entry.get("output_preview") or ""),
        "sidecar_path": entry.get("sidecar_path"),
        "status": str(entry.get("status") or ""),
        "error": entry.get("error"),
    }


def _entry_payload_sha256(entry: dict[str, Any]) -> str:
    return _payload_sha256(_hash_material_from_entry(entry))


def _write_output_sidecar(
    quest_root: Path,
    *,
    evidence_id: str,
    output_text: str,
) -> tuple[str | None, str]:
    content = str(output_text or "")
    if len(content.encode("utf-8", errors="replace")) <= _OUTPUT_SIDECAR_THRESHOLD_BYTES:
        return None, content
    sidecar_path = _sidecar_dir(quest_root) / f"{evidence_id}_output.txt"
    ensure_dir(sidecar_path.parent)
    sidecar_path.write_text(content, encoding="utf-8")
    relative = sidecar_path.relative_to(quest_root).as_posix()
    return relative, content


def _load_store(quest_root: Path) -> dict[str, Any]:
    path = _store_path(quest_root)
    payload = read_json(path, {})
    if not isinstance(payload, dict):
        payload = {}
    entries = payload.get("entries")
    if not isinstance(entries, list):
        entries = []
    return {
        "schema_version": str(payload.get("schema_version") or EVIDENCE_SCHEMA_VERSION),
        "generated_at": str(payload.get("generated_at") or utc_now()),
        "updated_at": str(payload.get("updated_at") or utc_now()),
        "quest_root": str(payload.get("quest_root") or str(quest_root)),
        "total_entries": int(payload.get("total_entries") or len(entries)),
        "entries": [item for item in entries if isinstance(item, dict)],
    }


def _save_store(quest_root: Path, store: dict[str, Any]) -> Path:
    path = _store_path(quest_root)
    ensure_dir(path.parent)
    store["schema_version"] = EVIDENCE_SCHEMA_VERSION
    store["quest_root"] = str(quest_root)
    store["updated_at"] = utc_now()
    store["total_entries"] = len(store.get("entries") or [])
    write_json(path, store)
    return path


def _entry_missing_required_fields(entry: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in _REQUIRED_ENTRY_FIELDS:
        if field not in entry:
            missing.append(field)
    return missing


def get_evidence_by_id(quest_root: Path, evidence_id: str) -> dict[str, Any] | None:
    target = str(evidence_id or "").strip()
    if not target:
        return None
    store = _load_store(quest_root)
    for entry in (store.get("entries") or []):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("evidence_id") or "").strip() == target:
            return dict(entry)
    return None


def validate_store(quest_root: Path) -> dict[str, Any]:
    store = _load_store(quest_root)
    errors: list[str] = []
    warnings: list[str] = []
    entries = [dict(item) for item in (store.get("entries") or []) if isinstance(item, dict)]
    if str(store.get("schema_version") or "") != EVIDENCE_SCHEMA_VERSION:
        errors.append(
            f"schema_version mismatch: expected {EVIDENCE_SCHEMA_VERSION}, got {store.get('schema_version')}"
        )

    seen_evidence_ids: set[str] = set()
    seen_event_ids: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        label = f"entry[{index}]"
        missing_fields = _entry_missing_required_fields(entry)
        for field in missing_fields:
            errors.append(f"{label} missing required field `{field}`")
        evidence_id = str(entry.get("evidence_id") or "").strip()
        if not evidence_id:
            errors.append(f"{label} empty evidence_id")
        elif evidence_id in seen_evidence_ids:
            errors.append(f"{label} duplicate evidence_id `{evidence_id}`")
        else:
            seen_evidence_ids.add(evidence_id)
        event_id = str(entry.get("event_id") or "").strip()
        if event_id:
            if event_id in seen_event_ids:
                errors.append(f"{label} duplicate event_id `{event_id}`")
            else:
                seen_event_ids.add(event_id)
        source_ref = entry.get("source_ref")
        if not isinstance(source_ref, dict):
            errors.append(f"{label} source_ref must be object")
        else:
            for key in ("kind", "path", "line", "url", "page", "sidecar_path"):
                if key not in source_ref:
                    errors.append(f"{label} source_ref missing `{key}`")
        expected_hash = _entry_payload_sha256(entry)
        actual_hash = str(entry.get("payload_sha256") or "")
        if expected_hash != actual_hash:
            errors.append(f"{label} payload_sha256 mismatch")
        sidecar_path = str(entry.get("sidecar_path") or "").strip()
        if sidecar_path:
            candidate = quest_root / Path(sidecar_path)
            if not candidate.exists():
                errors.append(f"{label} sidecar_path does not exist: {sidecar_path}")
        if str(entry.get("event_type") or "") not in {"runner.tool_call", "runner.tool_result"}:
            warnings.append(f"{label} unexpected event_type `{entry.get('event_type')}`")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "total_entries": len(entries),
    }


def _build_evidence_entry_with_quest_root(
    quest_root: Path,
    *,
    event: dict[str, Any],
    run_id: str,
    index: int,
) -> dict[str, Any]:
    created_at = str(event.get("created_at") or utc_now())
    event_id = str(event.get("event_id") or "").strip()
    tool_call_id = str(event.get("tool_call_id") or "").strip()
    tool_name = str(event.get("tool_name") or event.get("mcp_tool") or "tool").strip() or "tool"
    event_type = str(event.get("type") or "").strip()
    raw_status = str(event.get("status") or "").strip().lower()
    error_text = str(event.get("error") or event.get("error_message") or "").strip() or None
    status = "error" if raw_status in {"failed", "error", "cancelled", "canceled"} or error_text else "ok"
    evidence_packet = dict(event.get("evidence_packet") or {}) if isinstance(event.get("evidence_packet"), dict) else {}
    args = _json_or_raw(event.get("args"))
    output_text = _output_text(event.get("output"))
    evidence_id = f"ev_{run_id}_{index:06d}"
    sidecar_path = str(evidence_packet.get("sidecar_path") or "").strip() or None
    if not sidecar_path:
        sidecar_path, _ = _write_output_sidecar(quest_root, evidence_id=evidence_id, output_text=output_text)
    source_type = "evidence_packet_sidecar" if sidecar_path else "runner_tool_event"
    entry = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_id": evidence_id,
        "run_id": str(run_id),
        "event_id": event_id or None,
        "tool_call_id": tool_call_id or None,
        "event_type": event_type or None,
        "tool_name": tool_name,
        "created_at": created_at,
        "source_type": source_type,
        "source_ref": _source_ref_for_event(event, evidence_packet, sidecar_path=sidecar_path),
        "args": args,
        "output_preview": _output_preview(output_text),
        "summary": str(evidence_packet.get("summary") or "").strip() or None,
        "sidecar_path": sidecar_path,
        "status": status,
        "error": error_text,
        "recorded_at": utc_now(),
    }
    entry["payload_sha256"] = _entry_payload_sha256(entry)
    return entry


def _reindex_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        indexed.append(dict(entry))
    return indexed


def record_event(quest_root: Path, *, run_id: str, event: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    event_type = str(event.get("type") or "").strip()
    if event_type not in {"runner.tool_call", "runner.tool_result"}:
        return None

    store = _load_store(quest_root)
    entries = list(store.get("entries") or [])
    event_id = str(event.get("event_id") or "").strip()
    if event_id and any(str(item.get("event_id") or "") == event_id for item in entries):
        return None

    next_index = len(entries) + 1
    entry = _build_evidence_entry_with_quest_root(
        quest_root,
        event=event,
        run_id=run_id,
        index=next_index,
    )
    entries.append(entry)
    store["entries"] = _reindex_entries(entries)
    store["generated_at"] = str(store.get("generated_at") or utc_now())
    _save_store(quest_root, store)
    return entry


def query_events(
    quest_root: Path,
    *,
    run_id: str | None = None,
    tool_name: str | None = None,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    store = _load_store(quest_root)
    entries = [dict(item) for item in (store.get("entries") or []) if isinstance(item, dict)]
    if run_id:
        entries = [item for item in entries if str(item.get("run_id") or "") == str(run_id)]
    if tool_name:
        normalized = str(tool_name).strip().lower()
        entries = [item for item in entries if str(item.get("tool_name") or "").strip().lower() == normalized]
    if event_type:
        normalized = str(event_type).strip().lower()
        entries = [item for item in entries if str(item.get("event_type") or "").strip().lower() == normalized]
    return entries


def export_store(quest_root: Path) -> dict[str, Any]:
    store = _load_store(quest_root)
    # Repair payload hashes to keep exported store self-consistent.
    repaired_entries: list[dict[str, Any]] = []
    for entry in (store.get("entries") or []):
        if not isinstance(entry, dict):
            continue
        repaired = dict(entry)
        if "schema_version" not in repaired:
            repaired["schema_version"] = EVIDENCE_SCHEMA_VERSION
        if "args" not in repaired:
            repaired["args"] = {}
        if "output_preview" not in repaired:
            repaired["output_preview"] = ""
        if "source_ref" not in repaired or not isinstance(repaired.get("source_ref"), dict):
            repaired["source_ref"] = {
                "kind": "stdout",
                "path": _DEFAULT_SOURCE_PATH,
                "line": None,
                "url": None,
                "page": None,
                "sidecar_path": repaired.get("sidecar_path"),
            }
        repaired["payload_sha256"] = _entry_payload_sha256(repaired)
        repaired_entries.append(repaired)
    store["entries"] = repaired_entries
    path = _save_store(quest_root, store)
    return {
        "ok": True,
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "path": str(path),
        "total_entries": int(store.get("total_entries") or 0),
        "updated_at": str(store.get("updated_at") or utc_now()),
    }
