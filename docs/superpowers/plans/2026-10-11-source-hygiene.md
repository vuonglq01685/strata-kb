# Source hygiene (3e-2) implementation plan

Spec: `docs/superpowers/specs/2026-10-11-source-hygiene-design.md`.

- [x] **1. Guard test first.**
  - Add `tests/test_source_hygiene.py` with the docstring test and the provenance test.
  - Check that it fails on the current tree: 40 modules have no docstring, and about 450 provenance lines match.
- [x] **2. Rewrite by file group.** The groups touch disjoint files.
  - Group A: `intake.py` and `web/`.
  - Group B: `publish.py`, `pubgate.py`, `cipublish.py`, `hub.py`, `federation.py`, `gitio.py`, `ghio.py`, `ghapp.py`, `hashsync.py`.
  - Group C: `codeingest/`.
  - Group D: `assetstore.py`, `assetcmd.py`, `doctor/`, `svcnote.py`, `searchdb.py`, `query.py`, `resolve.py`, `kbcontext.py`, `summarize.py`, `review.py`.
  - Group E1: `cli.py`, `serving/`, `mcp.py`, `usage/`, `initcmd.py`, `models.py`, `errors.py`, `config.py`, `embed.py`, `utf8io.py`, `__init__.py`.
  - Group E2: `ingest/`, `mdutils.py`, the lint modules, `ticketstale.py`, `ticket.py`, `llm.py`, `dockersetup.py`, `acquality.py`, `diff.py`, `build.py`.
- [x] **3. Check that only comments and docstrings changed.**
  - Compare each changed module's AST with docstrings stripped against the base.
  - The ASTs must be equal.
- [x] **4. Run the full suite and T0.**
- [x] **5. Release 1.16.1:** CHANGELOG, `pyproject.toml`, `uv.lock`.
