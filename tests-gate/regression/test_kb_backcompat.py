"""Version MỚI phải đọc được .kb/ do version CŨ sinh ra.

Đây là hợp đồng đắt nhất của dự án: user đã commit .kb/ vào repo của họ. Đổi
schema mà không migrate là làm vỡ hết.

ĐỎ NGHĨA LÀ GÌ — và ĐỪNG SỬA TEST CHO XANH. Phải chọn một trong hai:
  (a) viết migration để version mới đọc được định dạng cũ, hoặc
  (b) đánh dấu xfail kèm ghi chú nêu rõ version nào phá và user phải làm gì.
Không có quy tắc này thì cửa sẽ bị tắt tiếng dần trong ba tháng.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml


def _clone_hub(hub: Path, dest: Path) -> Path:
    """Clone bare hub ra một working tree để đọc được nội dung đã push."""
    subprocess.run(
        ["git", "clone", "--quiet", str(hub), str(dest)],
        check=True, capture_output=True, text=True,
    )
    return dest


def test_new_binary_publishes_a_legacy_kb(legacy_kb, kb_run, tmp_path: Path):
    """Publish không chỉ phải exit 0 — nó phải MIRROR đúng .kb nguồn lên hub.

    `kb_run` mặc định check=True nên assert returncode==0 là code chết (đã
    raise trước khi test body chạy tiếp). Cái đáng sợ hơn nhiều là publish
    "thành công" (exit 0) nhưng âm thầm rơi rụng section hoặc ghi entry cụt —
    nên test này đọc lại chính bản đã publish trên hub và so với nguồn.
    """
    kb_run(
        "publish", "--direct", "--hub", str(legacy_kb["hub"]),
        "--repo-id", "legacy", "--kb-dir", str(legacy_kb["kb"]),
        cwd=legacy_kb["repo"],
    )

    clone = _clone_hub(legacy_kb["hub"], tmp_path / "hub-clone")
    published = clone / "federation" / "legacy"
    assert published.is_dir(), (
        f"{legacy_kb['tag']}: publish exit 0 nhưng federation/legacy/ "
        "không xuất hiện trên hub"
    )

    source_kb = legacy_kb["kb"]
    doc_ids = sorted(
        p.name for p in source_kb.iterdir()
        if p.is_dir() and (p / "_manifest.yaml").exists()
    )
    assert doc_ids, f"{legacy_kb['tag']}: .kb nguồn không có doc nào — fixture hỏng?"

    for doc_id in doc_ids:
        src_doc = source_kb / doc_id
        pub_doc = published / doc_id
        assert pub_doc.is_dir(), (
            f"{legacy_kb['tag']}: doc '{doc_id}' có trong .kb nguồn nhưng "
            "không xuất hiện trong federation/legacy đã publish — doc bị "
            "rơi rụng lặng lẽ?"
        )

        src_manifest = yaml.safe_load(
            (src_doc / "_manifest.yaml").read_text(encoding="utf-8")
        )
        pub_manifest = yaml.safe_load(
            (pub_doc / "_manifest.yaml").read_text(encoding="utf-8")
        )
        src_sections = src_manifest.get("sections", [])
        pub_sections = pub_manifest.get("sections", [])
        assert len(pub_sections) == len(src_sections), (
            f"{legacy_kb['tag']}/{doc_id}: manifest đã publish có "
            f"{len(pub_sections)} section, nguồn có {len(src_sections)} — "
            "section bị nuốt lặng lẽ khi publish?"
        )

        l2_files = sorted(
            f for f in src_doc.glob("*.md") if not f.name.endswith(".raw.md")
        )
        l3_files = sorted(src_doc.glob("*.raw.md"))
        assert l2_files and l3_files, (
            f"{legacy_kb['tag']}/{doc_id}: nguồn không có file L2/L3 nào — "
            "fixture hỏng?"
        )
        for src_file in l2_files + l3_files:
            pub_file = pub_doc / src_file.name
            assert pub_file.exists(), (
                f"{legacy_kb['tag']}/{doc_id}: file '{src_file.name}' có ở "
                "nguồn nhưng không có trong bản publish"
            )
            src_bytes = src_file.read_bytes()
            assert src_bytes, (
                f"{legacy_kb['tag']}/{doc_id}: file nguồn '{src_file.name}' "
                "rỗng — fixture hỏng?"
            )
            pub_bytes = pub_file.read_bytes()
            assert pub_bytes == src_bytes, (
                f"{legacy_kb['tag']}/{doc_id}: nội dung '{src_file.name}' đã "
                "publish khác nội dung nguồn — publish phải là mirror, "
                "không phải transform"
            )


def test_new_binary_runs_doctor_on_a_legacy_kb(legacy_kb, kb_run):
    """Chỉ "không có Traceback" là sàn quá thấp: một lỗi đọc schema mà product
    bắt được và báo sạch bằng `[error] ...` cũng không in Traceback, exit 1,
    và vẫn qua test đó. Phải khẳng định doctor thực sự đọc được .kb cũ — tức
    là in đúng dòng `kb doctor: OK` (chỉ in khi không có issue cấp error/stale).
    """
    kb_run("publish", "--direct", "--hub", str(legacy_kb["hub"]),
           "--repo-id", "legacy", "--kb-dir", str(legacy_kb["kb"]),
           cwd=legacy_kb["repo"])

    proc = kb_run("doctor", "--hub", str(legacy_kb["hub"]),
                  "--kb-dir", str(legacy_kb["kb"]),
                  cwd=legacy_kb["repo"], check=False)

    assert "Traceback" not in proc.stdout + proc.stderr, (
        f"doctor vỡ trên .kb của {legacy_kb['tag']}"
    )
    assert "kb doctor: OK" in proc.stdout, (
        f"doctor không in 'kb doctor: OK' trên .kb của {legacy_kb['tag']} — "
        f"doctor đọc .kb cũ nhưng không xác nhận nó lành, hay chỉ đơn giản "
        f"là không crash?\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )


def test_new_binary_queries_a_legacy_kb(legacy_kb, kb_run):
    kb_run("publish", "--direct", "--hub", str(legacy_kb["hub"]),
           "--repo-id", "legacy", "--kb-dir", str(legacy_kb["kb"]),
           cwd=legacy_kb["repo"])

    proc = kb_run("query", "airspace", "--hub", str(legacy_kb["hub"]),
                  "--kb-dir", str(legacy_kb["kb"]), cwd=legacy_kb["repo"])

    assert "No matching section found." not in proc.stdout, (
        f"query trên .kb của {legacy_kb['tag']} không trả về gì — "
        "section bị nuốt lặng?"
    )
