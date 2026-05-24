from __future__ import annotations

import json
from pathlib import Path

from deepscientist.evidence_chain import (
    EVIDENCE_SCHEMA_VERSION,
    export_store,
    get_evidence_by_id,
    query_events,
    record_event,
    validate_store,
)
from deepscientist.shared import read_json


def _quest_root(tmp_path: Path) -> Path:
    root = tmp_path / "quest"
    (root / ".ds").mkdir(parents=True, exist_ok=True)
    return root


def test_tool_call_can_be_recorded(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    entry = record_event(
        quest_root,
        run_id="run-a",
        event={
            "event_id": "evt-1",
            "type": "runner.tool_call",
            "tool_call_id": "call-1",
            "tool_name": "artifact.record",
            "created_at": "2026-05-24T10:00:00+00:00",
        },
    )
    assert entry is not None
    assert entry["event_type"] == "runner.tool_call"
    assert entry["status"] == "ok"


def test_tool_result_can_be_recorded(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    entry = record_event(
        quest_root,
        run_id="run-a",
        event={
            "event_id": "evt-2",
            "type": "runner.tool_result",
            "tool_call_id": "call-1",
            "tool_name": "artifact.get_quest_state",
            "output": "{\"ok\":true}",
        },
    )
    assert entry is not None
    assert entry["event_type"] == "runner.tool_result"
    assert entry["output_preview"]


def test_evidence_packet_sidecar_is_detected(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    entry = record_event(
        quest_root,
        run_id="run-a",
        event={
            "event_id": "evt-3",
            "type": "runner.tool_result",
            "tool_call_id": "call-2",
            "tool_name": "bash_exec.bash_exec",
            "evidence_packet": {
                "sidecar_path": ".ds/evidence_packets/run-a/some.json",
                "payload_sha256": "abc",
            },
        },
    )
    assert entry is not None
    assert entry["source_type"] == "evidence_packet_sidecar"
    assert entry["source_ref"]["sidecar_path"] == ".ds/evidence_packets/run-a/some.json"


def test_duplicate_event_id_is_deduped(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    payload = {
        "event_id": "evt-dup",
        "type": "runner.tool_result",
        "tool_call_id": "call-3",
        "tool_name": "tool-x",
    }
    first = record_event(quest_root, run_id="run-a", event=payload)
    second = record_event(quest_root, run_id="run-a", event=payload)
    assert first is not None
    assert second is None
    assert len(query_events(quest_root)) == 1


def test_missing_tool_call_id_does_not_crash(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    entry = record_event(
        quest_root,
        run_id="run-a",
        event={
            "event_id": "evt-4",
            "type": "runner.tool_result",
            "tool_name": "tool-y",
            "output": "ok",
        },
    )
    assert entry is not None
    assert entry["tool_call_id"] is None


def test_failed_tool_call_records_error_status(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    entry = record_event(
        quest_root,
        run_id="run-a",
        event={
            "event_id": "evt-5",
            "type": "runner.tool_result",
            "tool_call_id": "call-5",
            "tool_name": "bash_exec.bash_exec",
            "status": "failed",
            "error": "command failed",
        },
    )
    assert entry is not None
    assert entry["status"] == "error"
    assert entry["error"] == "command failed"


def test_large_output_writes_sidecar(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    long_output = "x" * 5000
    entry = record_event(
        quest_root,
        run_id="run-a",
        event={
            "event_id": "evt-6",
            "type": "runner.tool_result",
            "tool_call_id": "call-6",
            "tool_name": "tool-large",
            "output": long_output,
        },
    )
    assert entry is not None
    assert entry["sidecar_path"]
    assert (quest_root / entry["sidecar_path"]).exists()


def test_query_filters_work(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    record_event(
        quest_root,
        run_id="run-a",
        event={"event_id": "evt-7", "type": "runner.tool_call", "tool_call_id": "c1", "tool_name": "tool-a"},
    )
    record_event(
        quest_root,
        run_id="run-b",
        event={"event_id": "evt-8", "type": "runner.tool_result", "tool_call_id": "c2", "tool_name": "tool-b"},
    )
    assert len(query_events(quest_root, run_id="run-a")) == 1
    assert len(query_events(quest_root, tool_name="tool-b")) == 1
    assert len(query_events(quest_root, event_type="runner.tool_result")) == 1


def test_get_evidence_by_id_returns_exact_entry(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    entry = record_event(
        quest_root,
        run_id="run-a",
        event={"event_id": "evt-9", "type": "runner.tool_call", "tool_call_id": "c9", "tool_name": "tool-z"},
    )
    assert entry is not None
    found = get_evidence_by_id(quest_root, entry["evidence_id"])
    assert found is not None
    assert found["event_id"] == "evt-9"
    assert get_evidence_by_id(quest_root, "not-found") is None


def test_validate_store_detects_bad_data(tmp_path: Path) -> None:
    quest_root = _quest_root(tmp_path)
    record_event(
        quest_root,
        run_id="run-a",
        event={"event_id": "evt-10", "type": "runner.tool_call", "tool_call_id": "c10", "tool_name": "tool-ok"},
    )
    export_store(quest_root)
    store_path = quest_root / ".ds" / "evidence" / "evidence_store.json"
    store = read_json(store_path, {})
    assert store.get("schema_version") == EVIDENCE_SCHEMA_VERSION
    entries = store.get("entries") or []
    entries[0]["payload_sha256"] = "corrupted"
    entries[0]["sidecar_path"] = "missing/file.txt"
    store["entries"] = entries
    store_path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")

    report = validate_store(quest_root)
    assert report["ok"] is False
    assert any("payload_sha256 mismatch" in item for item in report["errors"])
    assert any("sidecar_path does not exist" in item for item in report["errors"])
