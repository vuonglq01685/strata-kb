import subprocess
from pathlib import Path

import pytest

from center_kb import models


def pytest_addoption(parser):
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="also run the tests that download a real embedding model",
    )


TABLE = "| Code | Meaning |\n|---|---|\n| P | Prohibited |\n| R | Restricted |"

L2_CONTENT = f"""## 1.1 Airspace Records

Condensed: airspace record structure with designation and type fields.

{TABLE}

## 1.2 Airway Records

Condensed: airway record structure, route identifiers.
"""

L3_CONTENT = f"""## 1.1 Airspace Records

Full raw text about airspace records. Designation, type, multiple code, level.

{TABLE}

## 1.2 Airway Records

Full raw text about airway records and route identifiers.
"""


@pytest.fixture
def fixture_kb(tmp_path: Path) -> Path:
    kb = tmp_path / ".kb"
    doc_dir = kb / "demo-doc"
    doc_dir.mkdir(parents=True)
    (doc_dir / "ch1-records.md").write_text(L2_CONTENT, encoding="utf-8")
    (doc_dir / "ch1-records.raw.md").write_text(L3_CONTENT, encoding="utf-8")
    manifest = models.Manifest(
        id="demo-doc",
        title="Demo Document",
        revision="Rev 1",
        sections=[
            models.SectionEntry(
                id="1.1",
                title="Airspace Records",
                summary="Airspace record structure: designation, type, level.",
                status="summarized",
                file="ch1-records",
            ),
            models.SectionEntry(
                id="1.2",
                title="Airway Records",
                summary="Airway record structure and route identifiers.",
                status="summarized",
                file="ch1-records",
            ),
        ],
    )
    models.save_yaml_model(doc_dir / "_manifest.yaml", manifest)
    index = models.KBIndex(
        docs=[
            models.IndexEntry(
                id="demo-doc",
                title="Demo Document",
                revision="Rev 1",
                tags=["demo", "airspace"],
                summary="Demo aviation data spec.",
            )
        ]
    )
    models.save_yaml_model(kb / "index.yaml", index)
    return kb


@pytest.fixture
def run_git():
    """Callable that runs git in a directory, with a fixed identity for tests."""

    def _run(root: Path, *args: str) -> str:
        proc = subprocess.run(
            [
                "git",
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@test.local",
                # Ignore the dev machine's global excludesFile (e.g. *.md ignored
                # globally) so the git fixtures don't depend on the test runner's gitconfig.
                "-c",
                "core.excludesFile=",
                *args,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()

    return _run


@pytest.fixture
def git_kb(fixture_kb: Path, run_git) -> dict:
    """Git repo containing .kb/ with 2 commits — simulates an amendment.

    Commit 1 (rev1): KB as in fixture_kb — the moment the BA wrote the requirement.
    Commit 2 (rev2 = HEAD): §1.1's L2 content + summary changed (amendment merged).
    Returns: {"root", "kb", "rev1", "rev2"}.
    """
    root = fixture_kb.parent
    run_git(root, "init")
    run_git(root, "config", "user.name", "test")
    run_git(root, "config", "user.email", "test@test.local")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "kb v1")
    rev1 = run_git(root, "rev-parse", "--short", "HEAD")

    l2 = fixture_kb / "demo-doc" / "ch1-records.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "airspace record structure with designation and type fields.",
            "airspace record structure with NEW multiple code field.",
        ),
        encoding="utf-8",
    )
    manifest_path = fixture_kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].summary = (
        "Airspace record structure: designation, type, multiple code."
    )
    models.save_yaml_model(manifest_path, manifest)
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "kb v2 - amendment 1.1")
    rev2 = run_git(root, "rev-parse", "--short", "HEAD")
    return {"root": root, "kb": fixture_kb, "rev1": rev1, "rev2": rev2}


HUB_L2 = """## 5.3 Restrictive Airspace

Restrictive airspace records: designation, type, multiple code, level.

| Type | Meaning |
|---|---|
| P | Prohibited |
| R | Restricted |
"""


@pytest.fixture
def hub_worktree(tmp_path: Path, run_git) -> Path:
    """Hub repo worktree: .kb/ has 1 domain doc 'arinc-424' + is git committed."""
    hub = tmp_path / "kb-hub"
    doc_dir = hub / ".kb" / "arinc-424"
    doc_dir.mkdir(parents=True)
    (doc_dir / "ch5-airspace.md").write_text(HUB_L2, encoding="utf-8")
    (doc_dir / "ch5-airspace.raw.md").write_text(HUB_L2, encoding="utf-8")
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id="arinc-424",
            title="ARINC 424",
            revision="Supplement 22",
            sections=[
                models.SectionEntry(
                    id="5.3",
                    title="Restrictive Airspace",
                    summary="Restrictive airspace: designation, type, multiple code.",
                    status="reviewed",
                    file="ch5-airspace",
                )
            ],
        ),
    )
    models.save_yaml_model(
        hub / ".kb" / "index.yaml",
        models.KBIndex(
            docs=[
                models.IndexEntry(
                    id="arinc-424",
                    title="ARINC 424",
                    revision="Supplement 22",
                    tags=["arinc424", "airspace"],
                    summary="Navigation database spec.",
                )
            ]
        ),
    )
    (hub / "federation").mkdir()
    (hub / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    run_git(hub, "init")
    run_git(hub, "config", "user.name", "test")
    run_git(hub, "config", "user.email", "test@test.local")
    run_git(hub, "add", "-A")
    run_git(hub, "commit", "-m", "hub v1")
    return hub


def make_fed_entry(
    federation_dir: Path,
    repo_id: str,
    doc_id: str,
    *,
    title: str = "",
    tags: list[str] | None = None,
    summary: str = "Doc summary.",
    sec_id: str = "1.1",
    sec_title: str = "Section One",
    sec_summary: str = "Summary of section one.",
    l2: str | None = None,
    l3: str | None = None,
    source_commit: str = "abc1234",
    published_at: str = "2026-07-13T00:00:00+00:00",
) -> Path:
    """Write one federation entry in the new format (full .kb mirror, L0→L3)."""
    from center_kb.federation import FederationMeta

    entry = federation_dir / repo_id
    doc_dir = entry / doc_id
    doc_dir.mkdir(parents=True)
    body_l2 = l2 if l2 is not None else (
        f"## {sec_id} {sec_title}\n\nCondensed content of {doc_id} {sec_id}.\n"
    )
    body_l3 = l3 if l3 is not None else (
        f"## {sec_id} {sec_title}\n\nVerbatim content of {doc_id} {sec_id}.\n"
    )
    (doc_dir / "ch1.md").write_text(body_l2, encoding="utf-8")
    (doc_dir / "ch1.raw.md").write_text(body_l3, encoding="utf-8")
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id=doc_id,
            title=title or doc_id,
            sections=[
                models.SectionEntry(
                    id=sec_id, title=sec_title, summary=sec_summary,
                    status="summarized", file="ch1",
                )
            ],
        ),
    )
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(
            docs=[
                models.IndexEntry(
                    id=doc_id, title=title or doc_id, tags=tags or [], summary=summary,
                )
            ]
        ),
    )
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(
            repo_id=repo_id, source_commit=source_commit, published_at=published_at,
        ),
    )
    return entry


@pytest.fixture
def fed_hub(tmp_path: Path, run_git) -> Path:
    """Hub git repo: federation/ has 2 published repos (mirror layout) + an
    aggregate index."""
    from center_kb.federation import write_federation_index

    hub = tmp_path / "kb-hub"
    (hub / ".kb").mkdir(parents=True)
    models.save_yaml_model(hub / ".kb" / "index.yaml", models.KBIndex())
    fed = hub / "federation"
    make_fed_entry(
        fed, "icao-kb", "icao-annex-2",
        tags=["icao", "airspace"],
        sec_id="1.1", sec_title="Airspace Records",
        sec_summary="Airspace record structure: designation, type, level.",
        l2="## 1.1 Airspace Records\n\nCondensed: airspace designation and type fields.\n",
        l3="## 1.1 Airspace Records\n\nFull raw text about airspace designation.\n",
    )
    make_fed_entry(
        fed, "arinc-kb", "arinc-424",
        tags=["arinc424"],
        sec_id="5.3", sec_title="Restrictive Airspace",
        sec_summary="Restrictive airspace: designation, type, multiple code.",
        l2="## 5.3 Restrictive Airspace\n\nCondensed: restrictive airspace designation codes.\n",
        l3="## 5.3 Restrictive Airspace\n\nFull raw restrictive airspace text.\n",
    )
    write_federation_index(fed)
    run_git(hub, "init")
    run_git(hub, "config", "user.name", "test")
    run_git(hub, "config", "user.email", "test@test.local")
    run_git(hub, "add", "-A")
    run_git(hub, "commit", "-m", "hub v1")
    return hub
