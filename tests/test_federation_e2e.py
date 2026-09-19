"""E2E: publish-first lifecycle — the hub federation is the single source of truth."""
from pathlib import Path

from typer.testing import CliRunner

from strata_kb import models
from strata_kb.cli import app
from strata_kb.mdutils import count_tokens, slice_section

runner = CliRunner()


def _make_repo(base: Path, run_git, name: str, doc_id: str, sec_id: str, keyword: str, hub: Path) -> Path:
    root = base / name
    kb = root / ".kb"
    doc = kb / doc_id
    doc.mkdir(parents=True)
    l2_text = f"## {sec_id} Title\n\nCondensed {keyword} content.\n"
    l3_text = f"## {sec_id} Title\n\nVerbatim {keyword} content.\n"
    (doc / "ch1.md").write_text(l2_text, encoding="utf-8")
    (doc / "ch1.raw.md").write_text(l3_text, encoding="utf-8")
    models.save_yaml_model(
        doc / "_manifest.yaml",
        models.Manifest(
            id=doc_id, title=doc_id,
            sections=[models.SectionEntry(
                id=sec_id, title="Title", summary=f"{keyword} summary.",
                status="summarized", file="ch1",
                # Real counts, not the 0/0 default -- doctor now recounts
                # L2/L3 tokens and reports drift (M9).
                tokens=models.SectionTokens(
                    l2=count_tokens(slice_section(l2_text, sec_id)),
                    l3=count_tokens(slice_section(l3_text, sec_id)),
                ),
            )],
        ),
    )
    models.save_yaml_model(
        kb / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(
            id=doc_id, title=doc_id, tags=[name], summary=f"{keyword} doc.",
        )]),
    )
    (kb / "config.yaml").write_text(
        f"hub: {hub}\nrepo_id: {name}\n", encoding="utf-8"
    )
    run_git(root, "init")
    run_git(root, "config", "user.name", "t")
    run_git(root, "config", "user.email", "t@t")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "v1")
    return root


def _make_hub(base: Path, run_git) -> Path:
    hub = base / "kb-hub"
    (hub / ".kb").mkdir(parents=True)
    models.save_yaml_model(hub / ".kb" / "index.yaml", models.KBIndex())
    (hub / "federation").mkdir()
    (hub / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    run_git(hub, "init")
    run_git(hub, "config", "user.name", "t")
    run_git(hub, "config", "user.email", "t@t")
    run_git(hub, "add", "-A")
    run_git(hub, "commit", "-m", "hub v0")
    return hub


def test_full_lifecycle(tmp_path, run_git):
    hub = _make_hub(tmp_path, run_git)
    repo_a = _make_repo(tmp_path, run_git, "repo-alpha", "alpha-spec", "1.1", "alpha widget", hub)
    repo_b = _make_repo(tmp_path, run_git, "repo-beta", "beta-spec", "2.1", "beta gadget", hub)

    # 1) publish both repos (direct — local-path hub); hub config from .kb/config.yaml
    for repo in (repo_a, repo_b):
        r = runner.invoke(app, ["publish", "--kb-dir", str(repo / ".kb")])
        assert r.exit_code == 0, r.output

    # 2) the aggregate index holds both repos
    idx = models.load_yaml_model(hub / "federation" / "index.yaml", models.FederationIndex)
    assert {(e.repo_id, e.doc_id) for e in idx.docs} == {
        ("repo-alpha", "alpha-spec"), ("repo-beta", "beta-spec"),
    }

    # 3) cross-repo search from repo A finds repo B's doc, with full L2
    r = runner.invoke(app, ["query", "beta gadget", "--kb-dir", str(repo_a / ".kb")])
    assert r.exit_code == 0, r.output
    assert "repo-beta:beta-spec §2.1" in r.output
    assert "Condensed beta gadget" in r.output

    # 4) get L3 verbatim via the hub
    r = runner.invoke(
        app, ["get", "beta-spec", "2.1", "--level", "l3", "--kb-dir", str(repo_a / ".kb")]
    )
    assert r.exit_code == 0, r.output
    assert "Verbatim beta gadget" in r.output

    # 5) context new pin HEAD hub + ref auto-qualified; resolve ok
    r = runner.invoke(
        app,
        ["context", "new", "--refs", "beta-spec §2.1", "--kb-dir", str(repo_a / ".kb")],
    )
    assert r.exit_code == 0, r.output
    block = r.output
    assert "- repo-beta:beta-spec §2.1" in block
    hub_head = run_git(hub, "rev-parse", "--short", "HEAD")
    assert f'version: "{hub_head}"' in block

    ticket = tmp_path / "ticket.md"
    ticket.write_text(block, encoding="utf-8")
    r = runner.invoke(app, ["resolve", str(ticket), "--kb-dir", str(repo_a / ".kb")])
    assert r.exit_code == 0, r.output
    assert "status=ok" in r.output

    # 6) amend repo B + republish → resolve stale (exit 2)
    l2 = repo_b / ".kb" / "beta-spec" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace("Condensed beta", "Condensed AMENDED beta"),
        encoding="utf-8",
    )
    run_git(repo_b, "add", "-A")
    run_git(repo_b, "commit", "-m", "amendment")
    r = runner.invoke(app, ["publish", "--kb-dir", str(repo_b / ".kb")])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["resolve", str(ticket), "--kb-dir", str(repo_a / ".kb")])
    assert r.exit_code == 2, r.output
    assert "stale" in r.output

    # 7) doctor catches the out-of-sync index, reindex fixes it
    (hub / "federation" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    r = runner.invoke(app, ["doctor", "--kb-dir", str(repo_a / ".kb")])
    assert r.exit_code == 1
    assert "kb reindex" in r.output
    r = runner.invoke(app, ["reindex", "--kb-dir", str(repo_a / ".kb")])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["doctor", "--kb-dir", str(repo_a / ".kb")])
    assert r.exit_code == 0, r.output
