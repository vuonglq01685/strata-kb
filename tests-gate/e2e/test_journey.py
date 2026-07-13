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


def test_publish_mirrors_all_levels_into_the_hub(published_repo, run_git, tmp_path):
    checkout = tmp_path / "hub-check"
    run_git(tmp_path, "clone", str(published_repo["hub"]), str(checkout))

    # federation/<repo-id>/ mirror toàn bộ .kb/ nguồn — cùng layout, nên
    # read_manifest/l2_path (đã dùng ở test_summarize_then_build) đọc thẳng
    # được từ đây thay vì đoán cứng tên tệp.
    mirror = checkout / "federation" / "e2e-repo"
    assert (mirror / "demo-doc" / "_manifest.yaml").exists()

    manifest = read_manifest(mirror)
    l2 = l2_path(mirror, manifest)
    assert l2.exists(), "thiếu L2"
    l3 = l2.with_name(f"{l2.stem}.raw.md")
    assert l3.exists(), "thiếu L3 (.raw.md)"
    assert (mirror / "_meta.yaml").exists()
    assert (checkout / "federation" / "index.yaml").exists()

    # Tồn tại file không đủ — publish copy rỗng/sai nội dung vẫn qua được các
    # assert phía trên. Soi nội dung: L2 phải là bản tóm tắt do stub_claude
    # sinh ra (cùng literal với test_summarize_then_build), L3 phải là văn
    # bản gốc verbatim (cùng literal "multiple code" với
    # test_get_returns_both_levels, lấy từ fixtures/pending-kb/.../*.raw.md).
    # Hai nội dung phải khác nhau — đó chính là lý do tách lớp L2/L3.
    l2_text = l2.read_text(encoding="utf-8")
    l3_text = l3.read_text(encoding="utf-8")
    assert "Condensed via stub." in l2_text, "L2 thiếu bản tóm tắt"
    assert "multiple code" in l3_text, "L3 phải verbatim, không phải tóm tắt"
    assert l2_text != l3_text


def test_doctor_is_clean_after_publish(published_repo, kb_run):
    proc = kb_run("doctor", "--hub", str(published_repo["hub"]),
                  "--kb-dir", str(published_repo["kb"]),
                  cwd=published_repo["repo"])

    # returncode == 0 không đủ để phân biệt "publish sạch" với "chưa publish
    # bao giờ": kb doctor chỉ đổi exit code khi có issue mức error hoặc
    # stale — issue mức warning (vd. "repo ... has not published to the hub
    # yet") vẫn để exit 0 VÀ vẫn in "kb doctor: OK" phía sau (xem
    # cli.py::doctor — dòng in "OK" không kiểm tra warning). Nên phải soi
    # thẳng stdout: sau một `kb publish` đúng, repo này phải sạch tuyệt đối —
    # không một dòng [warning]/[error] nào.
    assert proc.returncode == 0, proc.stdout
    assert "kb doctor: OK" in proc.stdout, proc.stdout
    assert "[warning]" not in proc.stdout, proc.stdout
    assert "[error]" not in proc.stdout, proc.stdout


def test_query_reads_from_the_hub(published_repo, kb_run):
    proc = kb_run("query", "airspace", "--hub", str(published_repo["hub"]),
                  "--kb-dir", str(published_repo["kb"]),
                  cwd=published_repo["repo"])

    assert "No matching section found." not in proc.stdout
    assert "Condensed via stub." in proc.stdout


def test_get_returns_both_levels(published_repo, kb_run):
    repo, kb, hub = published_repo["repo"], published_repo["kb"], published_repo["hub"]

    l2 = kb_run("get", "demo-doc", "1.1", "--level", "l2",
                "--hub", str(hub), "--kb-dir", str(kb), cwd=repo).stdout
    l3 = kb_run("get", "demo-doc", "1.1", "--level", "l3",
                "--hub", str(hub), "--kb-dir", str(kb), cwd=repo).stdout

    assert "Condensed via stub." in l2
    assert "multiple code" in l3, "L3 phải là verbatim, không phải bản tóm tắt"


def test_context_new_then_resolve_roundtrip(published_repo, kb_run, tmp_path):
    repo, kb, hub = published_repo["repo"], published_repo["kb"], published_repo["hub"]

    block = kb_run("context", "new", "--refs", "demo-doc §1.1",
                   "--hub", str(hub), "--kb-dir", str(kb), cwd=repo).stdout
    assert "kb-context" in block

    block_file = tmp_path / "ticket.md"
    block_file.write_text(block, encoding="utf-8")

    proc = kb_run("resolve", str(block_file), "--hub", str(hub),
                  "--kb-dir", str(kb), cwd=repo, check=False)

    # exit 0 = ok, 2 = stale, 1 = broken. Vừa pin xong thì phải là ok.
    assert proc.returncode == 0, f"resolve → {proc.returncode}\n{proc.stdout}"
    assert "Condensed via stub." in proc.stdout


def test_diff_detects_a_changed_section(published_repo, kb_run):
    repo, kb = published_repo["repo"], published_repo["kb"]
    manifest = read_manifest(kb)
    l2 = l2_path(kb, manifest)
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "Condensed via stub.", "Condensed via stub. Amended."
        ),
        encoding="utf-8",
    )

    # kb diff là local-git: so worktree với một git rev.
    proc = kb_run("diff", "demo-doc", "--against", "HEAD",
                  "--kb-dir", str(kb), cwd=repo)

    assert "1.1" in proc.stdout


def test_ingest_without_docling_fails_cleanly(kb_run, seed_kb, bare_hub, tmp_path):
    """Wheel base KHÔNG có extras [ingest]. User `pip install center-kb` rồi
    chạy ingest sẽ đâm vào đúng đường này — nó phải là một câu tiếng người,
    không phải traceback."""
    kb_run("init", cwd=tmp_path)
    seed_kb(tmp_path, bare_hub)
    fake_pdf = tmp_path / "x.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4\n")

    proc = kb_run("ingest", str(fake_pdf), "--id", "whatever",
                  cwd=tmp_path, check=False)

    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "Docling is not installed" in combined
    assert "Traceback" not in combined, (
        "ingest thiếu docling ném traceback thô vào mặt user:\n" + combined
    )
