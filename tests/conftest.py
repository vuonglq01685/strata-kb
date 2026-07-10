import subprocess
from pathlib import Path

import pytest

from aero_kb import models

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
    """Callable chạy git trong một thư mục, identity cố định cho test."""

    def _run(root: Path, *args: str) -> str:
        proc = subprocess.run(
            [
                "git",
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@test.local",
                # Bỏ qua global excludesFile của máy dev (vd: *.md bị ignore
                # global) để fixture git độc lập với gitconfig người chạy test.
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
    """Git repo chứa .kb/ với 2 commit — mô phỏng amendment.

    Commit 1 (rev1): KB như fixture_kb — thời điểm BA viết requirement.
    Commit 2 (rev2 = HEAD): §1.1 đổi nội dung L2 + summary (amendment đã merge).
    Trả về: {"root", "kb", "rev1", "rev2"}.
    """
    root = fixture_kb.parent
    run_git(root, "init")
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
    """Hub repo worktree: .kb/ có 1 doc domain 'arinc-424' + đã git commit."""
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
