"""Hành trình e2e đầy đủ trên wheel đã cài.

KHÔNG import center_kb ở đây. Artifact là hộp đen, chỉ chạm qua subprocess.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# tests-gate/e2e/test_journey.py → lùi 2 cấp là gốc repo.
REPO_ROOT = Path(__file__).parent.parent.parent


def read_manifest(kb: Path) -> dict:
    return yaml.safe_load((kb / "demo-doc" / "_manifest.yaml").read_text(encoding="utf-8"))


def l2_path(kb: Path, manifest: dict) -> Path:
    """Đường dẫn file L2 chứa section đầu tiên.

    Tên tệp (vd. 'ch1-airspace-records') là chi tiết triển khai của
    scaffold_doc() (suy ra từ tiêu đề chương) — đọc lại từ manifest thay vì
    đoán cứng, để test không trôi theo cách slugify() đặt tên tệp.
    """
    stem = manifest["sections"][0]["file"]
    return kb / "demo-doc" / f"{stem}.md"


def test_version_and_help(kb_run, tmp_path):
    version = kb_run("--version", cwd=tmp_path).stdout.strip()
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # Đọc pyproject như file text — KHÔNG import center_kb.
    declared = next(
        line.split("=", 1)[1].strip().strip('"')
        for line in pyproject.splitlines()
        if line.startswith("version =")
    )
    assert version == declared

    help_out = kb_run("--help", cwd=tmp_path).stdout
    expected = [
        "init", "ingest", "summarize", "status", "build", "query", "get",
        "stats", "publish", "reindex", "resolve", "diff", "doctor", "context",
    ]
    for name in expected:
        assert name in help_out, f"lệnh '{name}' biến mất khỏi wheel"


def test_init_scaffolds_a_kb(kb_run, tmp_path):
    kb_run("init", cwd=tmp_path)

    assert (tmp_path / ".kb" / "index.yaml").exists()
    assert (tmp_path / ".kb" / "config.yaml").exists()


def test_summarize_then_build(kb_run, seed_kb, stub_claude, bare_hub, tmp_path):
    kb_run("init", cwd=tmp_path)
    kb = seed_kb(tmp_path, bare_hub)

    before = read_manifest(kb)
    assert all(s["status"] == "pending" for s in before["sections"])
    assert "TODO:summarize" in l2_path(kb, before).read_text(encoding="utf-8")

    kb_run("summarize", "--llm", "claude", "--kb-dir", str(kb),
           cwd=tmp_path, env=stub_claude)

    after = read_manifest(kb)
    assert all(s["status"] == "summarized" for s in after["sections"])
    l2 = l2_path(kb, after).read_text(encoding="utf-8")
    assert "TODO:summarize" not in l2
    assert "Condensed via stub." in l2

    # kb build là LOCAL (validate không còn TODO) — chạy trước publish.
    out = kb_run("build", "--kb-dir", str(kb), cwd=tmp_path).stdout
    assert "kb build: OK" in out
