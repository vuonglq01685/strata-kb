"""The NEW version must be able to read a .kb/ produced by an OLD version.

This is the most expensive contract the project has: users have committed .kb/
into their own repos. Changing the schema without migrating breaks all of them.

WHAT RED MEANS — and DO NOT EDIT THE TEST TO MAKE IT GREEN. You must pick one of
two options:
  (a) write a migration so the new version can read the old format, or
  (b) mark it xfail with a note stating exactly which version broke it and what
      the user has to do.
Without this rule, the gate will be quietly silenced within three months.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml


def _clone_hub(hub: Path, dest: Path) -> Path:
    """Clone the bare hub into a working tree so the pushed content is readable."""
    subprocess.run(
        ["git", "clone", "--quiet", str(hub), str(dest)],
        check=True, capture_output=True, text=True,
    )
    return dest


def test_new_binary_publishes_a_legacy_kb(legacy_kb, kb_run, tmp_path: Path):
    """Publish must not merely exit 0 — it must MIRROR the source .kb onto the hub.

    `kb_run` defaults to check=True, so asserting returncode==0 would be dead
    code (it already raised before the test body could continue). The far scarier
    case is a publish that "succeeds" (exit 0) while silently dropping sections
    or writing a truncated entry — so this test reads back the very copy
    published on the hub and compares it against the source.
    """
    kb_run(
        "publish", "--direct", "--hub", str(legacy_kb["hub"]),
        "--repo-id", "legacy", "--kb-dir", str(legacy_kb["kb"]),
        cwd=legacy_kb["repo"],
    )

    clone = _clone_hub(legacy_kb["hub"], tmp_path / "hub-clone")
    published = clone / "federation" / "legacy"
    assert published.is_dir(), (
        f"{legacy_kb['tag']}: publish exited 0 but federation/legacy/ "
        "did not show up on the hub"
    )

    source_kb = legacy_kb["kb"]
    doc_ids = sorted(
        p.name for p in source_kb.iterdir()
        if p.is_dir() and (p / "_manifest.yaml").exists()
    )
    assert doc_ids, (
        f"{legacy_kb['tag']}: the source .kb has no docs at all — broken fixture?"
    )

    for doc_id in doc_ids:
        src_doc = source_kb / doc_id
        pub_doc = published / doc_id
        assert pub_doc.is_dir(), (
            f"{legacy_kb['tag']}: doc '{doc_id}' is in the source .kb but did "
            "not show up in the published federation/legacy — was the doc "
            "silently dropped?"
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
            f"{legacy_kb['tag']}/{doc_id}: the published manifest has "
            f"{len(pub_sections)} sections, the source has {len(src_sections)} — "
            "were sections silently swallowed during publish?"
        )

        l2_files = sorted(
            f for f in src_doc.glob("*.md") if not f.name.endswith(".raw.md")
        )
        l3_files = sorted(src_doc.glob("*.raw.md"))
        assert l2_files and l3_files, (
            f"{legacy_kb['tag']}/{doc_id}: the source has no L2/L3 files at "
            "all — broken fixture?"
        )
        for src_file in l2_files + l3_files:
            pub_file = pub_doc / src_file.name
            assert pub_file.exists(), (
                f"{legacy_kb['tag']}/{doc_id}: file '{src_file.name}' exists in "
                "the source but not in the published copy"
            )
            src_bytes = src_file.read_bytes()
            assert src_bytes, (
                f"{legacy_kb['tag']}/{doc_id}: source file '{src_file.name}' is "
                "empty — broken fixture?"
            )
            pub_bytes = pub_file.read_bytes()
            assert pub_bytes == src_bytes, (
                f"{legacy_kb['tag']}/{doc_id}: the published content of "
                f"'{src_file.name}' differs from the source content — publish "
                "must be a mirror, not a transform"
            )


def test_new_binary_runs_doctor_on_a_legacy_kb(legacy_kb, kb_run, strip_kind_warning):
    """Merely "no Traceback" is far too low a bar: a schema-reading failure that
    the product catches and reports cleanly as `[error] ...` also prints no
    Traceback, exits 1, and still passes that test. We must assert that doctor
    genuinely read the old .kb — i.e. that it printed the exact `kb doctor: OK`
    line (only printed when there is no error/stale-level issue).

    But the "kb doctor: OK" line alone is still not enough either: see
    cli.py::doctor — the "OK" line only checks that there is no error/stale-level
    issue, it does NOT check whether there is a warning-level issue. An old
    `.kb/` that the new version reads only half correctly — emitting
    `[warning] ...` — still slips past that OK line. (A real example: skipping the
    `kb publish` step makes `check_hub` emit "repo has not published to the hub
    yet" at warning level — not error level — so OK still prints as usual.) That
    is why we must inspect stdout directly: after a correct `kb publish`, the old
    .kb must be absolutely clean — not a single [warning]/[error] line.

    One deliberate exception: the "repo kind is not recorded" warning. Legacy
    configs predate role-aware init, so doctor warning about the missing
    `kind:` is the DESIGNED upgrade nudge, not a mis-read — see KIND_WARNING
    in tests-gate/conftest.py.
    """
    kb_run("publish", "--direct", "--hub", str(legacy_kb["hub"]),
           "--repo-id", "legacy", "--kb-dir", str(legacy_kb["kb"]),
           cwd=legacy_kb["repo"])

    proc = kb_run("doctor", "--hub", str(legacy_kb["hub"]),
                  "--kb-dir", str(legacy_kb["kb"]),
                  cwd=legacy_kb["repo"], check=False)

    assert "Traceback" not in proc.stdout + proc.stderr, (
        f"doctor blew up on the .kb of {legacy_kb['tag']}"
    )
    assert "kb doctor: OK" in proc.stdout, (
        f"doctor did not print 'kb doctor: OK' on the .kb of {legacy_kb['tag']} "
        f"— did doctor read the old .kb but decline to certify it healthy, or "
        f"did it merely not crash?"
        f"\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert "[warning]" not in strip_kind_warning(proc.stdout), (
        f"doctor printed 'kb doctor: OK' yet still emitted a [warning] on the "
        f".kb of {legacy_kb['tag']} — OK does not check for warnings (see "
        f"cli.py::doctor), so this is evidence the new version reads the old .kb "
        f"only partially correctly\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert "[error]" not in proc.stdout, (
        f"doctor printed 'kb doctor: OK' yet still emitted an [error] on the "
        f".kb of {legacy_kb['tag']}"
        f"\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )


def test_new_binary_queries_a_legacy_kb(legacy_kb, kb_run):
    kb_run("publish", "--direct", "--hub", str(legacy_kb["hub"]),
           "--repo-id", "legacy", "--kb-dir", str(legacy_kb["kb"]),
           cwd=legacy_kb["repo"])

    proc = kb_run("query", "leave", "--hub", str(legacy_kb["hub"]),
                  "--kb-dir", str(legacy_kb["kb"]), cwd=legacy_kb["repo"])

    assert "No matching section found." not in proc.stdout, (
        f"query against the .kb of {legacy_kb['tag']} returned nothing — were "
        "sections silently swallowed?"
    )
