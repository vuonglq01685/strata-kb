"""The full e2e journey against the installed wheel.

Do NOT import center_kb here. The artifact is a black box, only ever touched
through subprocess.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# tests-gate/e2e/test_journey.py → two levels up is the repo root.
REPO_ROOT = Path(__file__).parent.parent.parent


def read_manifest(kb: Path) -> dict:
    return yaml.safe_load((kb / "demo-doc" / "_manifest.yaml").read_text(encoding="utf-8"))


def l2_path(kb: Path, manifest: dict) -> Path:
    """Path to the L2 file holding the first section.

    The filename (e.g. 'ch1-airspace-records') is an implementation detail of
    scaffold_doc() (derived from the chapter title) — read it back from the
    manifest instead of hardcoding a guess, so the test does not drift with the
    way slugify() names files.
    """
    stem = manifest["sections"][0]["file"]
    return kb / "demo-doc" / f"{stem}.md"


def test_version_and_help(kb_run, tmp_path):
    version = kb_run("--version", cwd=tmp_path).stdout.strip()
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # Read pyproject as a text file — do NOT import center_kb.
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
        "tags",
    ]
    for name in expected:
        assert name in help_out, f"command '{name}' vanished from the wheel"


def test_init_scaffolds_a_kb(kb_run, tmp_path):
    kb_run("init", "--kind", "child", cwd=tmp_path)

    assert (tmp_path / ".kb" / "index.yaml").exists()
    assert (tmp_path / ".kb" / "config.yaml").exists()


def test_summarize_then_build(kb_run, seed_kb, stub_claude, bare_hub, tmp_path):
    kb_run("init", "--kind", "child", cwd=tmp_path)
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

    # kb build is LOCAL (validates that no TODO is left) — runs before publish.
    out = kb_run("build", "--kb-dir", str(kb), cwd=tmp_path).stdout
    assert "kb build: OK" in out


def test_publish_mirrors_all_levels_into_the_hub(published_repo, run_git, tmp_path):
    checkout = tmp_path / "hub-check"
    run_git(tmp_path, "clone", str(published_repo["hub"]), str(checkout))

    # federation/<repo-id>/ mirrors the whole source .kb/ — same layout, so
    # read_manifest/l2_path (already used in test_summarize_then_build) can read
    # straight from here instead of hardcoding filename guesses.
    mirror = checkout / "federation" / "e2e-repo"
    assert (mirror / "demo-doc" / "_manifest.yaml").exists()

    manifest = read_manifest(mirror)
    l2 = l2_path(mirror, manifest)
    assert l2.exists(), "L2 missing"
    l3 = l2.with_name(f"{l2.stem}.raw.md")
    assert l3.exists(), "L3 (.raw.md) missing"
    assert (mirror / "_meta.yaml").exists()
    assert (checkout / "federation" / "index.yaml").exists()

    # File existence is not enough — a publish that copied empty/wrong content
    # would still pass the asserts above. Inspect the content: L2 must be the
    # summary produced by stub_claude (the same literal as in
    # test_summarize_then_build), L3 must be the verbatim source text (the same
    # "multiple code" literal as in test_get_returns_both_levels, taken from
    # fixtures/pending-kb/.../*.raw.md). The two contents must differ — that is
    # precisely the reason the L2/L3 layers are split apart.
    l2_text = l2.read_text(encoding="utf-8")
    l3_text = l3.read_text(encoding="utf-8")
    assert "Condensed via stub." in l2_text, "L2 is missing the summary"
    assert "multiple code" in l3_text, "L3 must be verbatim, not a summary"
    assert l2_text != l3_text


def test_doctor_is_clean_after_publish(published_repo, kb_run):
    proc = kb_run("doctor", "--hub", str(published_repo["hub"]),
                  "--kb-dir", str(published_repo["kb"]),
                  cwd=published_repo["repo"])

    # returncode == 0 is not enough to tell "published cleanly" apart from
    # "never published at all": kb doctor only changes its exit code on issues at
    # error or stale level — a warning-level issue (e.g. "repo ... has not
    # published to the hub yet") still exits 0 AND still prints "kb doctor: OK"
    # afterwards (see cli.py::doctor — the line printing "OK" does not check for
    # warnings). So we have to inspect stdout directly: after a correct
    # `kb publish`, this repo must be absolutely clean — not a single
    # [warning]/[error] line.
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
    assert "multiple code" in l3, "L3 must be verbatim, not the summary"


def test_context_new_then_resolve_roundtrip(published_repo, kb_run, tmp_path):
    repo, kb, hub = published_repo["repo"], published_repo["kb"], published_repo["hub"]

    block = kb_run("context", "new", "--refs", "demo-doc §1.1",
                   "--hub", str(hub), "--kb-dir", str(kb), cwd=repo).stdout
    assert "kb-context" in block

    block_file = tmp_path / "ticket.md"
    block_file.write_text(block, encoding="utf-8")

    proc = kb_run("resolve", str(block_file), "--hub", str(hub),
                  "--kb-dir", str(kb), cwd=repo, check=False)

    # exit 0 = ok, 2 = stale, 1 = broken. Just pinned, so it must be ok.
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

    # kb diff is local-git: it compares the worktree against a git rev.
    proc = kb_run("diff", "demo-doc", "--against", "HEAD",
                  "--kb-dir", str(kb), cwd=repo)

    assert "1.1" in proc.stdout


def test_ingest_without_docling_fails_cleanly(kb_run, seed_kb, bare_hub, tmp_path):
    """The base wheel does NOT carry the [ingest] extras. A user who runs
    `pip install center-kb` and then runs ingest lands on exactly this path — it
    must be a human sentence, not a traceback."""
    kb_run("init", "--kind", "child", cwd=tmp_path)
    seed_kb(tmp_path, bare_hub)
    fake_pdf = tmp_path / "x.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4\n")

    proc = kb_run("ingest", str(fake_pdf), "--id", "whatever",
                  cwd=tmp_path, check=False)

    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "Docling is not installed" in combined
    assert "Traceback" not in combined, (
        "ingest without docling threw a raw traceback in the user's face:\n"
        + combined
    )
