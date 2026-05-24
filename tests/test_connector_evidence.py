"""Integration tests for connector evidence recording — Role C."""

from __future__ import annotations

from pathlib import Path

from deepscientist.evidence_audit import (
    audit_report,
    build_evidence_table,
    render_audit_markdown,
)
from deepscientist.evidence_chain import (
    query_events,
    record_connector_event,
)


def _setup_quest_root(tmp_path: Path) -> Path:
    root = tmp_path / "quest"
    (root / ".ds" / "evidence").mkdir(parents=True, exist_ok=True)
    return root


def _create_test_image(quest_root: Path, filename: str, size: tuple = (800, 600)) -> Path:
    from PIL import Image

    userfiles = quest_root / "userfiles" / "qq" / "test_batch"
    userfiles.mkdir(parents=True, exist_ok=True)
    path = userfiles / filename
    img = Image.new("RGB", size, color=(66, 133, 244))
    img.save(path, "PNG")
    return path


# --- Test 1: Text message ---

def test_text_message_generates_text_evidence(tmp_path: Path) -> None:
    quest_root = _setup_quest_root(tmp_path)

    message = {
        "text": "请帮我复现这篇论文的 Table 1",
        "sender_id": "user_001",
        "sender_name": "张三",
        "message_id": "msg_abc123",
        "conversation_id": "qq:direct:user_001",
        "created_at": "2026-05-24T12:00:00+00:00",
    }

    entries = record_connector_event(quest_root, message=message, materialized_attachments=[])

    assert len(entries) == 1
    entry = entries[0]
    assert entry["source_type"] == "connector_text"
    assert entry["evidence_id"].startswith("E0")
    assert entry["tool_name"] == "connector.qq"
    assert entry["status"] == "ok"
    assert entry["args"]["sender_name"] == "张三"
    assert entry["args"]["sender_id"] == "user_001"
    assert entry["args"]["conversation_id"] == "qq:direct:user_001"
    assert "Table 1" in entry["output_preview"]
    assert entry["payload_sha256"]

    # Audit compatibility
    report_text = f"用户请求复现实验 [{entry['evidence_id']}]"
    result = audit_report(report_text, quest_root)
    assert entry["evidence_id"] in result.cited_ids
    assert not result.fake_ids


# --- Test 2: Image message ---

def test_image_message_generates_image_evidence(tmp_path: Path) -> None:
    quest_root = _setup_quest_root(tmp_path)
    img_path = _create_test_image(quest_root, "test_chart.png", size=(800, 600))

    message = {
        "text": "",
        "sender_id": "user_002",
        "sender_name": "李四",
        "message_id": "msg_img001",
        "conversation_id": "qq:direct:user_002",
        "created_at": "2026-05-24T12:30:00+00:00",
    }

    quest_rel = "userfiles/qq/test_batch/test_chart.png"
    materialized = [
        {
            "name": "test_chart.png",
            "content_type": "image/png",
            "url": "https://qq.example.com/attachments/img_001",
            "path": str(img_path),
            "quest_relative_path": quest_rel,
            "size_bytes": img_path.stat().st_size,
            "materialized": True,
            "downloaded_at": "2026-05-24T12:30:05+00:00",
        }
    ]

    entries = record_connector_event(quest_root, message=message, materialized_attachments=materialized)

    # Should be 1 image entry (no text entry since text is empty)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["source_type"] == "connector_image"
    assert entry["evidence_id"].endswith("-img")
    assert entry["tool_name"] == "connector.qq.image"
    assert entry["status"] == "ok"

    # Image metadata
    assert entry["args"]["width"] == 800
    assert entry["args"]["height"] == 600
    assert entry["args"]["format"] == "PNG"
    assert entry["args"]["sha256"]
    assert entry["args"]["filename"] == "test_chart.png"
    assert entry["args"]["content_type"] == "image/png"
    assert entry["source_ref"]["kind"] == "connector_image"
    assert entry["source_ref"]["path"] == quest_rel

    # Audit should recognize E00X-img format
    report_text = f"实验数据图表如下 [{entry['evidence_id']}]"
    result = audit_report(report_text, quest_root)
    assert entry["evidence_id"] in result.cited_ids
    assert not result.fake_ids


# --- Test 3: Mixed text + image ---

def test_mixed_message_creates_both_entries(tmp_path: Path) -> None:
    quest_root = _setup_quest_root(tmp_path)
    img_path = _create_test_image(quest_root, "result.png", size=(1024, 768))

    message = {
        "text": "这是实验结果截图",
        "sender_id": "user_003",
        "sender_name": "王五",
        "message_id": "msg_mix001",
        "created_at": "2026-05-24T13:00:00+00:00",
    }

    materialized = [
        {
            "name": "result.png",
            "content_type": "image/png",
            "url": "https://qq.example.com/attachments/img_002",
            "path": str(img_path),
            "quest_relative_path": "userfiles/qq/test_batch/result.png",
            "size_bytes": img_path.stat().st_size,
            "materialized": True,
        }
    ]

    entries = record_connector_event(quest_root, message=message, materialized_attachments=materialized)

    assert len(entries) == 2
    text_entry = next(e for e in entries if e["source_type"] == "connector_text")
    img_entry = next(e for e in entries if e["source_type"] == "connector_image")

    assert text_entry["evidence_id"] == "E001"
    assert img_entry["evidence_id"] == "E001-img"
    assert text_entry["tool_name"] == "connector.qq"
    assert img_entry["tool_name"] == "connector.qq.image"

    # Sequential numbering: second call should produce E002, E002-img
    entries2 = record_connector_event(
        quest_root,
        message={**message, "text": "第二张图", "message_id": "msg_mix002"},
        materialized_attachments=materialized,
    )
    assert entries2[0]["evidence_id"] == "E002"
    assert entries2[1]["evidence_id"] == "E002-img"

    # Verify store has all 4 entries
    all_entries = query_events(quest_root)
    assert len(all_entries) == 4


# --- Test 4: Fake image ID detection ---

def test_audit_detects_fake_image_id(tmp_path: Path) -> None:
    quest_root = _setup_quest_root(tmp_path)
    img_path = _create_test_image(quest_root, "real_chart.png")

    message = {
        "text": "实验结果",
        "sender_id": "user_004",
        "sender_name": "赵六",
        "message_id": "msg_real001",
        "created_at": "2026-05-24T14:00:00+00:00",
    }

    materialized = [
        {
            "name": "real_chart.png",
            "content_type": "image/png",
            "path": str(img_path),
            "quest_relative_path": "userfiles/qq/test_batch/real_chart.png",
            "size_bytes": img_path.stat().st_size,
            "materialized": True,
        }
    ]

    entries = record_connector_event(quest_root, message=message, materialized_attachments=materialized)
    text_id = entries[0]["evidence_id"]
    img_id = entries[1]["evidence_id"]

    # Report cites real IDs + a fake one
    report = (
        f"实验准备工作已完成 [{text_id}]。"
        f"Figure 1 展示了结果 [{img_id}]。"
        f"补充细节见附录 [E999-img]。"
    )
    result = audit_report(report, quest_root)

    assert text_id in result.cited_ids
    assert img_id in result.cited_ids
    assert "E999-img" in result.fake_ids
    assert result.ok is False  # fake ID present


# --- Test 5: End-to-end ---

def test_end_to_end_message_to_audit_report(tmp_path: Path) -> None:
    quest_root = _setup_quest_root(tmp_path)
    img1 = _create_test_image(quest_root, "chart1.png", size=(800, 600))
    img2 = _create_test_image(quest_root, "chart2.png", size=(1200, 900))

    messages = [
        {
            "text": "开始实验",
            "message_id": "msg_seq001",
            "sender_id": "u1",
            "sender_name": "User1",
            "created_at": "2026-05-24T10:00:00+00:00",
        },
        {
            "text": "这是第一组结果",
            "message_id": "msg_seq002",
            "sender_id": "u1",
            "sender_name": "User1",
            "created_at": "2026-05-24T10:05:00+00:00",
        },
        {
            "text": "这是第二组结果",
            "message_id": "msg_seq003",
            "sender_id": "u2",
            "sender_name": "User2",
            "created_at": "2026-05-24T10:10:00+00:00",
        },
    ]

    def _att(path: Path, name: str) -> list[dict]:
        return [
            {
                "name": name,
                "content_type": "image/png",
                "path": str(path),
                "quest_relative_path": f"userfiles/qq/batch/{name}",
                "size_bytes": path.stat().st_size,
                "materialized": True,
            }
        ]

    attachments_groups = [
        [],  # msg1: text only
        _att(img1, "chart1.png"),
        _att(img2, "chart2.png"),
    ]

    all_ids: list[str] = []
    for msg, atts in zip(messages, attachments_groups):
        entries = record_connector_event(quest_root, message=msg, materialized_attachments=atts)
        all_ids.extend(e["evidence_id"] for e in entries)

    # 3 text + 2 image = 5 entries
    assert len(all_ids) == 5
    assert "E001" in all_ids
    assert "E001-img" not in all_ids  # msg1 had no image
    assert "E002" in all_ids and "E002-img" in all_ids
    assert "E003" in all_ids and "E003-img" in all_ids

    # Build a multi-claim report
    report = (
        f"实验准备工作已经全部完成 [E001]。\n"
        f"第一组实验结果显示在图表演示中 [E002-img]。\n"
        f"第二组结果验证了初步的研究假设 [E003][E003-img]。\n"
        f"注意力机制能够有效替代循环神经网络 [推断]。\n"
        f"这个实验结论完全可靠且无任何疑点。\n"
        f"未来还需要更多实验来进行验证 [待验证]。\n"
    )

    result = audit_report(report, quest_root)

    assert len(result.cited_ids) >= 4
    assert not result.fake_ids
    assert result.bare_sentence_count == 1  # "这个实验结论完全可靠且无任何疑点"
    assert result.inferred_count == 1  # "[推断]"
    assert result.unverified_count == 1  # "[待验证]"
    assert result.supported_count >= 3

    # Render audit markdown
    md = render_audit_markdown(result, quest_root)
    assert "Evidence Chain Audit" in md
    assert "PASS" in md

    # Build evidence table
    table = build_evidence_table(report, quest_root)
    assert "E001" in table
    assert "E002-img" in table
    assert "E003" in table
    assert "E003-img" in table
    assert "connector.qq" in table
    assert "connector.qq.image" in table
