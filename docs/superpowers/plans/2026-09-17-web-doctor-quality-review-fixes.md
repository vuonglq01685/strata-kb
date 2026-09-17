# Web + doctor + engineering-quality review fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `kb doctor` survive and report the corruptions it exists to
diagnose, and bring the HTTP surface (session, headers, rate limiting,
error pages) up to the standard the rest of the codebase already meets.

**Architecture:** One guard in the shared hub funnel (`_hub_or_exit`) fixes
clean-error handling for 11 commands at once. The `/ui` cookie becomes a
signed, expiring value derived from the token instead of the token itself.
One `SlidingWindowLimiter` instance is shared by the login form and the
`Authorization` path so the lockout cannot be side-stepped. `doctor` gains
four checks that reuse existing helpers (`mdutils.heading_occurrences`,
`mdutils.count_tokens`, `_fed_tree_digest`). No new dependency.

**Tech Stack:** Python 3.11+, typer/click, Starlette (raw ASGI middleware,
no framework extras), pydantic v2, pytest, ruff, hmac/hashlib from stdlib.

**Spec:** `docs/superpowers/specs/2026-09-17-web-doctor-quality-review-fixes-design.md`

## Global Constraints

- Release target **0.24.0**. Bump `pyproject.toml` version and add a
  CHANGELOG section in the final task, not per task.
- **No new dependency.** Everything uses stdlib (`hmac`, `hashlib`, `time`,
  `ast`) or what is already installed.
- **Every writer of committed content passes `newline="\n"`.** Task 15
  turns this into an enforced scan; do not regress it in earlier tasks.
- **`typer.echo`/`typer.secho` only in `cli.py`**; library modules use
  `logging.getLogger("center_kb.<mod>")`. `cipublish.py` is corrected in
  Task 17 — do not add new `print()` anywhere.
- **Exit codes after Task 8:** `0` ok, `1` error (including
  misconfiguration), `2` citation stale only. Click's own bad-flag errors
  also emit 2 and we do not control that.
- **`extra="forbid"` on authored models only.** `FedIndexEntry` and
  `FederationIndex` stay permissive — a 0.23 install must be able to read a
  0.24 hub.
- **Tests use real filesystems, real git repos and `monkeypatch`.** No
  `unittest.mock`, no `MagicMock` — the suite has none today and must keep
  none.
- Run tests with `.venv/Scripts/pytest` (this is a Windows machine; Git
  Bash resolves that path). `python -m pytest` also works inside the venv.
- Full suite is ~550 s / 1875 tests. Per-task runs target specific files;
  only the final task runs everything.

---

## File Structure

**New files:**

| File | Responsibility |
| --- | --- |
| `src/center_kb/web/headers.py` | One ASGI middleware that adds security response headers. Nothing else. |
| `tests/test_web_session.py` | Signed-session helpers, cookie flags, logout. |
| `tests/test_web_headers.py` | Header presence across status codes, HSTS conditionality, CSP shape. |
| `tests/test_web_auth_ratelimit.py` | The shared bucket: failed header auth counts, success does not, login and header share it. |
| `tests/test_web_snapshot_errors.py` | Corrupt federation manifest → JSON 503 on `/api`, error shell on `/ui`. |
| `tests/test_doctor_checks.py` | The four new doctor checks and the config-corruption path. |

**Modified files:**

| File | Change |
| --- | --- |
| `src/center_kb/cli.py` | Hoist `_CONFIG_READ_ERRORS`; guard `_hub_or_exit`; reorder doctor's `check_kind`; three fail-closed blocks; `status` guard; 8 exit-code flips; `--hub` help on 8 commands; stale note on `query`/`get`. |
| `src/center_kb/doctor.py` | Four new checks; `if repo_id:` unskip; optional newline normalisation in the two digests. |
| `src/center_kb/models.py` | `extra="forbid"` on `SectionEntry`, `Manifest`, `IndexEntry`, `KBIndex`; `content_sha256` on `FedIndexEntry`; comment on why the federation models stay permissive. |
| `src/center_kb/federation.py` | `build_federation_index` fills `content_sha256` per snapshot. |
| `src/center_kb/diff.py` | `title_changed` on `SectionChange`; order detection; render kinds. |
| `src/center_kb/query.py` | `QueryResult.content_tokens` alongside the existing budget `tokens`. |
| `src/center_kb/web/auth.py` | `make_session`/`verify_session`; `COOKIE_NAME`; limiter + trusted-proxy plumbing; `is_authorized_request` helper for `/api/health`. |
| `src/center_kb/web/app.py` | Build the shared limiter; wire both middlewares; register the snapshot-error handler. |
| `src/center_kb/web/ui.py` | Cookie flags + derived `Secure`; `/ui/logout`; login body cap; `no-store`; `content_tokens`. |
| `src/center_kb/web/api.py` | `SnapshotCorruptError`; health trim; `content_tokens`. |
| `src/center_kb/cipublish.py` | 6 bare `print()` → `typer.echo`. |
| `src/center_kb/hub.py` | `resolve_hub` docstring. |
| `scripts/gate.sh` | Platform-aware hint on the no-interpreter path. |
| `pyproject.toml` | ruff `select` + `per-file-ignores`; version bump. |
| `README.md` | Exit-code table; the `kb diff` line. |
| `docs/deploy-remote-mcp.md` | Stale CRLF note; security headers; `CENTER_KB_TRUSTED_PROXIES` and cookie `Secure`. |
| `tests/test_windows_hygiene.py` | Replace `COMMITTED_WRITERS` with an AST scan. |
| `tests/test_check_package.py` | Cover `installed_version`. |
| `tests/test_web_app.py` | `_sweep` test. |
| `CHANGELOG.md` | 0.24.0. |

---

### Task 1: Hoist `_CONFIG_READ_ERRORS` and guard the hub funnel

A corrupt `.kb/config.yaml` currently escapes `_hub_or_exit` as a rich
`pydantic.ValidationError` traceback, because that function only catches
`HubConfigError` and `gitio.GitError`. The error tuple it needs already
exists — but as a *local* re-declared in three command bodies
(`cli.py:1571`, `:1763`, `:1830`), so it must first become a module
constant.

**Files:**
- Modify: `src/center_kb/cli.py:397-433` (`_hub_or_exit`), `:1571`, `:1763`,
  `:1830` (delete the three locals), `:864-888` (`status`)
- Test: `tests/test_cli_doctor_diff.py`

**Interfaces:**
- Produces: module-level `_CONFIG_READ_ERRORS = (yaml.YAMLError,
  ValidationError, ValueError)` in `cli.py`, importable by later tasks as
  `from center_kb.cli import _CONFIG_READ_ERRORS` (they will not need to —
  they are in the same module).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_doctor_diff.py  (append)
def test_doctor_on_invalid_config_kind_is_a_clean_error_not_a_traceback(tmp_path):
    """H1: doctor must report an invalid config.yaml, not die producing it."""
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "index.yaml").write_text("docs: []\n", encoding="utf-8", newline="\n")
    (kb / "config.yaml").write_text(
        "hub: " + str(tmp_path / "hub") + "\nrepo_id: child\nkind: bogus\n",
        encoding="utf-8",
        newline="\n",
    )

    result = runner.invoke(app, ["doctor", "--kb-dir", str(kb)])

    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output
    assert "ValidationError" not in result.output
    assert "config.yaml" in result.output


def test_status_on_invalid_index_is_a_clean_error_not_a_traceback(tmp_path):
    """L29: kb status calls load_yaml_model unguarded — same class as H1."""
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "index.yaml").write_text("docs: [unclosed\n", encoding="utf-8", newline="\n")

    result = runner.invoke(app, ["status", "--kb-dir", str(kb)])

    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output
    assert "index.yaml" in result.output
```

If `runner`/`app` are not already imported in that file, add
`from typer.testing import CliRunner`, `from center_kb.cli import app`, and
`runner = CliRunner()` at the top — check first, the file already has them
for its existing tests.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_cli_doctor_diff.py -k "invalid_config_kind or invalid_index" -v`

Expected: FAIL — both show a `ValidationError`/`ParserError` traceback in
`result.output` (typer's `CliRunner` captures the rich traceback), so the
`"Traceback" not in result.output` assertion fails.

- [ ] **Step 3: Hoist the constant**

Near the top of `cli.py`, after the existing imports (`yaml` and
`ValidationError` are already imported there — verify; if `ValidationError`
is not, add `from pydantic import ValidationError`):

```python
# One tuple for every "an operator-authored YAML file did not parse or did
# not validate" read in this module. Was three identical locals inside
# publish(), ci_publish() and doctor() (each commenting at the other two);
# _hub_or_exit needs it too, which is what made the duplication untenable.
_CONFIG_READ_ERRORS = (yaml.YAMLError, ValidationError, ValueError)
```

Then delete the three local re-declarations at `cli.py:1571`, `:1763` and
`:1830` — the surrounding `except (*_CONFIG_READ_ERRORS, OSError)` clauses
keep working unchanged against the module constant. Leave their explanatory
comments, but point them at the module constant instead of at each other.

- [ ] **Step 4: Guard `_hub_or_exit`**

In `cli.py:397-433`, change the `require_hub` call:

```python
    try:
        hub_ref = require_hub(hub_flag, kb_dir)
    except HubConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    except (*_CONFIG_READ_ERRORS, OSError) as exc:
        # require_hub -> load_config -> models.load_yaml_model raises
        # ValidationError / yaml.YAMLError for an operator-edited
        # .kb/config.yaml. 11 commands funnel through here, so this is the
        # one place that keeps any of them from printing a traceback (H1).
        typer.secho(
            f"{kb_dir / 'config.yaml'} is invalid: {' '.join(str(exc).split())}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
```

- [ ] **Step 5: Guard `status`**

In `cli.py:864-888`, wrap the two `models.load_yaml_model` calls:

```python
    try:
        index = models.load_yaml_model(index_path, models.KBIndex)
    except (*_CONFIG_READ_ERRORS, OSError) as exc:
        typer.secho(
            f"{index_path} is invalid: {' '.join(str(exc).split())}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
```

and the manifest read inside the loop, with the manifest path in the
message. Keep the loop going for other docs? No — exit 1 on the first bad
file, matching every other command in this module.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_cli_doctor_diff.py tests/test_publish.py tests/test_cli_hub.py -q`

Expected: PASS. `test_publish.py` and `test_cli_hub.py` are the regression
guard for deleting the three locals.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/cli.py tests/test_cli_doctor_diff.py
git commit -m "fix(cli): one module-level _CONFIG_READ_ERRORS, guarded in the hub funnel (H1, L29)"
```

---

### Task 2: doctor checks its config before resolving the hub; three blocks fail closed

`check_kind` already returns `Issue("error", "config.yaml is invalid: …")`
(`doctor.py:119-126`) — it has simply been unreachable, because
`cli.py:2581` resolves the hub first. And three `except Exception` blocks in
doctor's hub branch fail *open* where `publish.py:1291-1294` fails closed on
the identical read.

**Files:**
- Modify: `src/center_kb/cli.py:2581-2582` (ordering), `:2588-2590`,
  `:2595-2597`, `:2626-2628` (fail closed)
- Test: `tests/test_doctor_checks.py` (create)

**Interfaces:**
- Consumes: `_CONFIG_READ_ERRORS` (Task 1).
- Produces: nothing new; behaviour only.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doctor_checks.py  (new file)
"""The doctor checks added by the reviewer-H batch (H1, M13, M9)."""
from pathlib import Path

from typer.testing import CliRunner

from center_kb.cli import app

runner = CliRunner()


def _minimal_kb(root: Path, kind: str = "child") -> Path:
    kb = root / ".kb"
    kb.mkdir(parents=True)
    (kb / "index.yaml").write_text("docs: []\n", encoding="utf-8", newline="\n")
    (kb / "config.yaml").write_text(
        f"hub: {root / 'hub'}\nrepo_id: child\nkind: {kind}\n",
        encoding="utf-8",
        newline="\n",
    )
    return kb


def test_doctor_reports_invalid_config_as_an_issue(tmp_path):
    """M13/H1: the message comes from doctor.check_kind, which means the
    check ran — not from _hub_or_exit's guard, which would mean it did not."""
    kb = _minimal_kb(tmp_path)
    (kb / "config.yaml").write_text(
        f"hub: {tmp_path / 'hub'}\nrepo_id: child\nkind: bogus\n",
        encoding="utf-8",
        newline="\n",
    )

    result = runner.invoke(app, ["doctor", "--kb-dir", str(kb)])

    assert result.exit_code == 1, result.output
    assert "[error] config.yaml is invalid" in result.output
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/pytest tests/test_doctor_checks.py -v`

Expected: FAIL — output carries `_hub_or_exit`'s `config.yaml is invalid:`
line from Task 1 but **not** the `[error] ` prefix, because `check_kind`
still never runs.

- [ ] **Step 3: Reorder, and keep the hub work after it**

In `cli.py`'s `doctor`, replace:

```python
    handle = _hub_or_exit(hub, kb_dir)
    issues = check_kind(kb_dir) + check_kb(kb_dir) + check_asset_store(kb_dir, handle)
```

with:

```python
    # check_kind first: it is the only check that can report a broken
    # config.yaml, and _hub_or_exit reads that same file to find the hub —
    # resolving first meant doctor exited before its own handler ran (H1).
    kind_issues = check_kind(kb_dir)
    if any(i.level == "error" for i in kind_issues):
        for issue in kind_issues:
            typer.secho(f"[{issue.level}] {issue.message}", fg=typer.colors.RED)
        raise typer.Exit(1)
    handle = _hub_or_exit(hub, kb_dir)
    issues = kind_issues + check_kb(kb_dir) + check_asset_store(kb_dir, handle)
```

- [ ] **Step 4: Flip the three blocks to fail closed**

`cli.py:2588-2590`:

```python
        try:
            from center_kb import gitio as _gitio

            repo_id = _gitio.git_root(kb_dir.resolve()).name
        except _gitio.GitError as exc:
            issues.append(
                Issue(
                    "error",
                    f"could not determine the repo id — .kb is not inside a git "
                    f"repo and repo_id is unset in config.yaml: {_flatten(exc)}",
                )
            )
            repo_id = None
```

`Issue` and `_flatten` need importing at the top of the `doctor` body
alongside the other `center_kb.doctor` imports: add `Issue` and
`_flatten` to that import list.

`cli.py:2595-2597` — the self-refuting `except Exception: pass`:

```python
    cfg_kind = ""
    try:
        from center_kb.config import load_config as _load_config

        cfg_kind = _load_config(kb_dir).kind
    except (*_CONFIG_READ_ERRORS, OSError) as exc:
        # Step 3 makes check_kind run first, so an invalid config already
        # exited above. Reaching here means something else (a permission
        # error, a vanished file) — doctor's job is to report it, not to
        # continue with an empty kind and silently skip the kind-specific
        # checks below.
        issues.append(
            Issue("error", f"could not read .kb/config.yaml: {_flatten(exc)}")
        )
```

`cli.py:2626-2628` — the upstream identity read, matching
`publish.py:1291-1294`'s wording:

```python
                try:
                    dest_rid = _load_config2(handle.kb_dir).repo_id
                except (*_CONFIG_READ_ERRORS, OSError) as exc:
                    # publish.py:1291 fails closed on this exact read
                    # ("a corrupt upstream config must not silently blind
                    # the cycle guard"). One condition, one policy.
                    issues.append(
                        Issue(
                            "error",
                            "could not read the upstream hub's .kb/config.yaml: "
                            f"{_flatten(exc)}",
                        )
                    )
                    dest_rid = ""
```

- [ ] **Step 5: Add tests for the two fail-closed paths**

```python
# tests/test_doctor_checks.py  (append)
def test_doctor_reports_an_unreadable_upstream_config_instead_of_skipping(
    tmp_path, monkeypatch
):
    """M13: publish.py fails closed on this read; doctor must too."""
    from center_kb import config as config_mod

    kb = _minimal_kb(tmp_path, kind="hub")
    real_load = config_mod.load_config

    def _boom(kb_dir, *a, **kw):
        if Path(kb_dir).resolve() != kb.resolve():
            raise OSError("permission denied")
        return real_load(kb_dir, *a, **kw)

    monkeypatch.setattr(config_mod, "load_config", _boom)
    result = runner.invoke(app, ["doctor", "--kb-dir", str(kb)])

    assert "could not read" in result.output
    assert result.exit_code == 1, result.output
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/pytest tests/test_doctor_checks.py tests/test_cli_doctor_diff.py tests/test_cli_hub.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/cli.py tests/test_doctor_checks.py
git commit -m "fix(doctor): check kind before resolving the hub; fail closed on unreadable configs (H1, M13)"
```

---

### Task 3: `extra="forbid"` on the authored models

A typo'd `sumary:` currently loads, the field takes its default, and every
L1 summary silently publishes as `""`. `RegistryEntry` (`models.py:115`)
already carries the fix with the rationale — copy it to the KB's own
models, and *not* to the federation wire format.

**Files:**
- Modify: `src/center_kb/models.py:37-46` (`SectionEntry`), `:56-63`
  (`Manifest`), `:66-71` (`IndexEntry`), `:82-84` (`KBIndex`), `:87-99`
  (comment on the federation models)
- Test: `tests/test_doctor_checks.py`

**Interfaces:**
- Produces: `Manifest`, `SectionEntry`, `IndexEntry`, `KBIndex` reject
  unknown keys with `pydantic.ValidationError`. `FedIndexEntry` and
  `FederationIndex` continue to ignore them.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doctor_checks.py  (append)
import pytest
from pydantic import ValidationError

from center_kb import models


def test_manifest_rejects_a_typod_key():
    """M10: 'sumary:' used to load and publish every summary as ''."""
    with pytest.raises(ValidationError):
        models.Manifest.model_validate(
            {
                "id": "d",
                "title": "T",
                "sections": [
                    {"id": "1", "title": "S", "file": "ch1", "sumary": "oops"}
                ],
            }
        )


def test_federation_index_still_accepts_unknown_keys():
    """Deliberate asymmetry: the federation index is the wire format between
    installs, and 0.24 adds a field to it — a 0.23 reader must not hard-error."""
    idx = models.FederationIndex.model_validate(
        {"docs": [{"repo_id": "r", "doc_id": "d", "future_field": "x"}]}
    )
    assert idx.docs[0].doc_id == "d"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/pytest tests/test_doctor_checks.py -k "typod_key or unknown_keys" -v`

Expected: the first test FAILS (`DID NOT RAISE ValidationError`); the second
already passes and is there to lock the asymmetry in.

- [ ] **Step 3: Add the config to the four authored models**

To `SectionEntry`, `Manifest`, `IndexEntry` and `KBIndex`, add as the first
line of each class body:

```python
    # extra="forbid", same reason as RegistryEntry below: a plausible
    # operator typo in an authored YAML file (`sumary:` for `summary:`)
    # used to validate cleanly, take the field's default, and publish an
    # empty L1 summary. `kb doctor` reported OK on it (M10).
    model_config = ConfigDict(extra="forbid")
```

Write the comment once in full on `SectionEntry` and reference it from the
other three (`# extra="forbid": see SectionEntry.`) — `ConfigDict` is
already imported at `models.py:8`.

On `FedIndexEntry`, add:

```python
    # NOT extra="forbid", unlike the authored models above: this file is
    # written by one install and read by others, and 0.24 added
    # content_sha256 to it. Forbidding unknown keys here would make every
    # older install hard-error on a hub a newer one published.
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/pytest tests/test_doctor_checks.py -q`

Expected: PASS.

- [ ] **Step 5: Run the broad regression set — this is the risky change**

Run: `.venv/Scripts/pytest tests/test_models.py tests/test_build.py tests/test_publish.py tests/test_federation_e2e.py tests/test_ingest_cli.py -q`

Then against the repo's own real data:

```bash
.venv/Scripts/kb doctor --kb-dir .kb
```

Expected: PASS, and `kb doctor` behaves exactly as it did before this task
(any *new* failure here means real KB data carries an unknown key — stop and
report it rather than loosening the model).

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/models.py tests/test_doctor_checks.py
git commit -m "fix(models): extra=forbid on authored models, permissive on the federation wire format (M10)"
```

---

### Task 4: doctor catches duplicate section ids and orphan headings

Two of M9's blind spots, both cheap: a duplicate id inside one doc, and a
`## ` heading in an L2/L3 file that the manifest does not list. `_check_doc`
already flags orphan *files* (`doctor.py:70-75`) but never reads headings
back out.

**Files:**
- Modify: `src/center_kb/doctor.py:34-76` (`_check_doc`)
- Test: `tests/test_doctor_checks.py`

**Interfaces:**
- Consumes: `mdutils.heading_ids(md, fence_aware=True)` →
  `list[str]` (exists, `mdutils.py:143`).
- Produces: two new `Issue("error", …)` messages, wording fixed by the
  tests below.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_doctor_checks.py  (append)
def _doc_with(kb: Path, doc_id: str, manifest_yaml: str, md: str) -> None:
    d = kb / doc_id
    d.mkdir(parents=True)
    (d / "_manifest.yaml").write_text(manifest_yaml, encoding="utf-8", newline="\n")
    (d / "ch1.md").write_text(md, encoding="utf-8", newline="\n")
    (d / "ch1.raw.md").write_text(md, encoding="utf-8", newline="\n")
    (kb / "index.yaml").write_text(
        f"docs:\n  - id: {doc_id}\n    title: T\n", encoding="utf-8", newline="\n"
    )


def test_duplicate_section_id_within_a_doc_is_an_error(tmp_path):
    from center_kb import doctor

    kb = _minimal_kb(tmp_path)
    _doc_with(
        kb,
        "d1",
        "id: d1\ntitle: T\nsections:\n"
        "  - {id: '2.1', title: A, file: ch1, status: reviewed}\n"
        "  - {id: '2.1', title: B, file: ch1, status: reviewed}\n",
        "## 2.1 A\nbody a\n\n## 2.1 B\nbody b\n",
    )

    issues = doctor.check_kb(kb)

    assert any(
        i.level == "error" and "duplicate section id" in i.message for i in issues
    ), issues


def test_heading_absent_from_the_manifest_is_an_error(tmp_path):
    from center_kb import doctor

    kb = _minimal_kb(tmp_path)
    _doc_with(
        kb,
        "d1",
        "id: d1\ntitle: T\nsections:\n"
        "  - {id: '2.1', title: A, file: ch1, status: reviewed}\n",
        "## 2.1 A\nbody a\n\n## 2.77 Orphan\nnot in the manifest\n",
    )

    issues = doctor.check_kb(kb)

    assert any(
        i.level == "error" and "2.77" in i.message and "not in _manifest.yaml" in i.message
        for i in issues
    ), issues
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/pytest tests/test_doctor_checks.py -k "duplicate_section_id or heading_absent" -v`

Expected: FAIL — `check_kb` returns no error for either corruption (this is
review rows #5 and #4).

- [ ] **Step 3: Implement both checks in `_check_doc`**

`Counter` is already imported at `doctor.py:4`. Add
`from center_kb.mdutils import heading_ids, slice_section` (extend the
existing `slice_section` import).

After the `for sec in manifest.sections:` loop, before the pending warning:

```python
    dupes = [sid for sid, n in Counter(s.id for s in manifest.sections).items() if n > 1]
    for sid in sorted(dupes):
        issues.append(
            Issue(
                "error",
                f"{doc_id} §{sid}: duplicate section id in _manifest.yaml — "
                "ids are the citation key and must be unique within a doc",
            )
        )

    # The manifest→file direction is checked above (missing file, unsliceable
    # section). This is the file→manifest direction for headings, the way the
    # orphan-file loop below is for files: a heading nothing lists is content
    # no citation can reach (M9, review row #4).
    listed = {s.id for s in manifest.sections}
    for suffix in (".md", ".raw.md"):
        for name in sorted({f"{s.file}{suffix}" for s in manifest.sections}):
            path = doc_dir / name
            if not path.exists():
                continue  # already reported above
            for sid in heading_ids(
                path.read_text(encoding="utf-8"), fence_aware=True
            ):
                if sid not in listed:
                    issues.append(
                        Issue(
                            "error",
                            f"{doc_id}: heading '{sid}' in '{name}' is not in "
                            "_manifest.yaml",
                        )
                    )
```

`fence_aware=True` matters: a `.raw.md` embedding source text whose body
contains a `##` line is not a document heading (Ruling R16, `mdutils.py:120`).

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/pytest tests/test_doctor_checks.py -q`

Expected: PASS.

- [ ] **Step 5: Run doctor against real data — these checks are new failures**

Run: `.venv/Scripts/pytest tests/test_cli_doctor_diff.py tests/test_federation_e2e.py -q && .venv/Scripts/kb doctor --kb-dir .kb`

Expected: PASS and `kb doctor: OK`. A failure here is a real finding in the
repo's own KB — report it, do not weaken the check.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/doctor.py tests/test_doctor_checks.py
git commit -m "feat(doctor): catch duplicate section ids and headings missing from the manifest (M9)"
```

---

### Task 5: doctor recounts token drift

Review row #9: `tokens: {l2: 99999, l3: 1}` passes with `kb doctor: OK`.
`kb build` recomputes these; doctor is what the README sells as the health
check.

**Files:**
- Modify: `src/center_kb/doctor.py:34-76` (`_check_doc`)
- Test: `tests/test_doctor_checks.py`

**Interfaces:**
- Consumes: `mdutils.count_tokens(text) -> int` (`mdutils.py:33`),
  `mdutils.slice_section(md, sid, occurrence)` (`mdutils.py:40`),
  `mdutils.heading_occurrences(sections) -> list[int]` (`mdutils.py:64`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doctor_checks.py  (append)
def test_stale_token_counts_are_an_error(tmp_path):
    from center_kb import doctor

    kb = _minimal_kb(tmp_path)
    _doc_with(
        kb,
        "d1",
        "id: d1\ntitle: T\nsections:\n"
        "  - id: '2.1'\n    title: A\n    file: ch1\n    status: reviewed\n"
        "    tokens: {l2: 99999, l3: 1}\n",
        "## 2.1 A\nbody a\n",
    )

    issues = doctor.check_kb(kb)

    assert any(
        i.level == "error" and "tokens.l2" in i.message and "kb build" in i.message
        for i in issues
    ), issues
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/pytest tests/test_doctor_checks.py -k stale_token -v`

Expected: FAIL — no issue mentions tokens.

- [ ] **Step 3: Implement the recount**

Ids are not unique within a file, so the slice must use the row's
occurrence index — that is exactly what `heading_occurrences` is for.
Inside `_check_doc`, replace the existing `for sec in manifest.sections:`
header with an enumerate over the occurrence list:

```python
    occurrences = heading_occurrences(manifest.sections)
    for row, sec in enumerate(manifest.sections):
        ...
            elif slice_section(
                path.read_text(encoding="utf-8"), sec.id, occurrences[row]
            ) is None:
```

(keep the existing body; only the `slice_section` call gains the third
argument). Then, still inside the `for suffix, layer in …` loop, after the
successful-slice branch:

```python
            else:
                sliced = slice_section(
                    path.read_text(encoding="utf-8"), sec.id, occurrences[row]
                )
                recount = count_tokens(sliced)
                stored = sec.tokens.l2 if suffix == ".md" else sec.tokens.l3
                field = "tokens.l2" if suffix == ".md" else "tokens.l3"
                if stored != recount:
                    issues.append(
                        Issue(
                            "error",
                            f"{doc_id} §{sec.id}: {field} is {stored}, recount is "
                            f"{recount} — run 'kb build'",
                        )
                    )
```

Extend the `mdutils` import with `count_tokens` and `heading_occurrences`.

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/pytest tests/test_doctor_checks.py -q`

Expected: PASS.

- [ ] **Step 5: Verify against real data and the build path**

Run: `.venv/Scripts/pytest tests/test_build.py tests/test_cli_doctor_diff.py -q && .venv/Scripts/kb doctor --kb-dir .kb`

Expected: PASS and `kb doctor: OK` — `kb build` keeps these counts current,
so the repo's own KB should agree exactly. A mismatch means the real data
has drifted; report the doc and section rather than relaxing the check.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/doctor.py tests/test_doctor_checks.py
git commit -m "feat(doctor): recount L2/L3 tokens and report drift (M9)"
```

---

### Task 6: hub content tampering is detectable

Review row #18: editing published L2 text in place on the hub passes with
`kb doctor: OK`. `check_hub`'s digest compare exists but (a) only runs when
`repo_id` is truthy and (b) compares a *local* `.kb` against its snapshot —
at the hub there is nothing local to compare against, so the hub needs a
digest of its own, stored at publish/reindex time.

**Files:**
- Modify: `src/center_kb/models.py:87-99` (`FedIndexEntry.content_sha256`),
  `src/center_kb/federation.py:290-312` (`build_federation_index`),
  `src/center_kb/doctor.py:664-703` (`check_hub`), `:727-748`
  (`_fed_tree_digest`), `src/center_kb/cli.py:2600-2604` (pass `repo_id`)
- Test: `tests/test_doctor_checks.py`, `tests/test_federation.py`

**Interfaces:**
- Consumes: `doctor._fed_tree_digest(root: Path) -> str` (already exists).
- Produces: `models.FedIndexEntry.content_sha256: str = ""`;
  `federation.entry_content_digest(entry_dir: Path) -> str` (thin re-export
  so `federation.py` does not import a private name from `doctor.py`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doctor_checks.py  (append)
def test_tampered_hub_content_is_an_error(tmp_path):
    """M9 row #18: editing a published L2 file in place used to pass."""
    from center_kb import doctor, federation

    fed = tmp_path / "hub" / "federation"
    entry = fed / "child"
    (entry / "d1").mkdir(parents=True)
    (entry / "_meta.yaml").write_text(
        "repo_id: child\nsource_commit: abc123\npublished_at: '2026-09-17'\n",
        encoding="utf-8",
        newline="\n",
    )
    (entry / "index.yaml").write_text(
        "docs:\n  - id: d1\n    title: T\n", encoding="utf-8", newline="\n"
    )
    (entry / "d1" / "_manifest.yaml").write_text(
        "id: d1\ntitle: T\nsections: []\n", encoding="utf-8", newline="\n"
    )
    (entry / "d1" / "ch1.md").write_text(
        "## 2.1 A\nbody\n", encoding="utf-8", newline="\n"
    )
    federation.write_federation_index(fed)

    # tamper: rewrite published content in place, leave the index alone
    (entry / "d1" / "ch1.md").write_text(
        "## 2.1 A\nTAMPERED\n", encoding="utf-8", newline="\n"
    )

    issues = doctor.check_published_digests(fed)

    assert any(
        i.level == "error" and "child" in i.message and "digest" in i.message
        for i in issues
    ), issues


def test_a_snapshot_without_a_stored_digest_is_skipped_with_a_note(tmp_path):
    """Pre-0.24 hubs stay green: absent field is not a failure."""
    from center_kb import doctor, federation

    fed = tmp_path / "hub" / "federation"
    entry = fed / "child"
    entry.mkdir(parents=True)
    (entry / "_meta.yaml").write_text(
        "repo_id: child\nsource_commit: abc\npublished_at: '2026-09-17'\n",
        encoding="utf-8",
        newline="\n",
    )
    (entry / "index.yaml").write_text(
        "docs:\n  - id: d1\n    title: T\n", encoding="utf-8", newline="\n"
    )
    federation.write_federation_index(fed)
    # strip the digests the way a 0.23 hub would never have written them
    text = (fed / "index.yaml").read_text(encoding="utf-8")
    stripped = "\n".join(
        ln for ln in text.splitlines() if "content_sha256" not in ln
    )
    (fed / "index.yaml").write_text(stripped + "\n", encoding="utf-8", newline="\n")

    issues = doctor.check_published_digests(fed)

    assert all(i.level != "error" for i in issues), issues
    assert any("not verified" in i.message for i in issues), issues
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/pytest tests/test_doctor_checks.py -k "tampered_hub or without_a_stored_digest" -v`

Expected: FAIL with `AttributeError: module 'center_kb.doctor' has no
attribute 'check_published_digests'`.

- [ ] **Step 3: Add the field and fill it**

`models.py`, on `FedIndexEntry` (after `published_at`):

```python
    # sha256 of the snapshot's own content tree (federation/<rid>/**),
    # written by reindex/publish so `kb doctor` at the HUB can detect
    # content edited in place — the hub has no local .kb to diff against
    # (M9 row #18). "" = published before 0.24, not verifiable.
    content_sha256: str = ""
```

`federation.py`, a small public wrapper plus the fill in
`build_federation_index`:

```python
def entry_content_digest(entry_dir: Path) -> str:
    """Digest of one snapshot's content tree — the value stored in
    federation/index.yaml as FedIndexEntry.content_sha256."""
    from center_kb.doctor import _fed_tree_digest

    return _fed_tree_digest(entry_dir)
```

and inside the `for repo in load_federation(federation_dir):` loop, hoist
one digest per repo (not per doc — it is a whole-entry digest):

```python
    for repo in load_federation(federation_dir):
        digest = entry_content_digest(repo.kb_dir)
        for doc in repo.index.docs:
            entries.append(
                models.FedIndexEntry(
                    ...
                    published_at=repo.meta.published_at,
                    content_sha256=digest,
                )
            )
```

The import is function-local on purpose: `doctor` imports `federation`
already, so a module-level import here would be circular.

- [ ] **Step 4: Add the checker and wire it in**

`doctor.py`, next to `_fed_tree_digest`:

```python
def check_published_digests(fed: Path) -> list[Issue]:
    """Compare each snapshot's content against the digest stored for it in
    federation/index.yaml. This is the only tamper check available at the
    hub: there is no local .kb there to diff against."""
    from center_kb.federation import FEDERATION_INDEX_NAME, entry_content_digest

    index_path = fed / FEDERATION_INDEX_NAME
    if not index_path.exists():
        return []  # missing index is reported by check_hub
    try:
        stored = models.load_yaml_model(index_path, models.FederationIndex)
    except (yaml.YAMLError, ValidationError):
        return []  # corruption is reported by check_hub
    expected: dict[str, str] = {}
    for doc in stored.docs:
        expected.setdefault(doc.repo_id, doc.content_sha256)

    issues: list[Issue] = []
    for repo_id, digest in sorted(expected.items()):
        entry = fed / repo_id
        if not entry.is_dir():
            continue  # reported by check_hub
        if not digest:
            issues.append(
                Issue(
                    "warning",
                    f"federation/{repo_id} was published before 0.24 — content "
                    "digest not verified; run `kb reindex` on the hub to record it",
                )
            )
            continue
        if entry_content_digest(entry) != digest:
            issues.append(
                Issue(
                    "error",
                    f"federation/{repo_id} content does not match its published "
                    "digest — the snapshot was modified outside `kb publish`",
                )
            )
    return issues
```

Call it from `check_hub`, right after the existing
`federation/index.yaml`-out-of-sync branch:

```python
    issues += check_published_digests(fed)
```

- [ ] **Step 5: Unskip the local compare at the hub**

In `cli.py`, the hub branch passes `repo_id=None`, which skips
`check_hub`'s `if repo_id:` snapshot comparison entirely:

```python
        hub_issues, hub_stale = check_hub(
            kb_dir, handle, repo_id=repo_id, warn_untracked_index=True
        )
```

A hub that also publishes its own `.kb` now gets the same
local-vs-published comparison a child does; a hub that does not have an
entry gets the existing "has not published to the hub yet" warning, which
is accurate.

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/pytest tests/test_doctor_checks.py tests/test_federation.py tests/test_federation_e2e.py tests/test_cli_hub.py -q`

Expected: PASS. If `test_federation*.py` pins `index.yaml` bytes, update
those expectations — the new key is intended.

- [ ] **Step 7: Optional — normalise newlines in the two digests (H3c)**

Only if the batch keeps this item. In both `_kb_tree_digest`
(`doctor.py:332`) and `_fed_tree_digest` (`:746`), replace
`path.read_bytes()` with:

```python
        # Legacy self-heal: a hub cache cloned before F-D10 (which now forces
        # core.autocrlf=false and ships .gitattributes) still has a CRLF
        # working tree, and neutralize_line_endings runs on clone, never on
        # pull. Normalising here keeps a byte-identical tree from reading as
        # drift until the TTL re-clone (H3c).
        h.update(path.read_bytes().replace(b"\r\n", b"\n"))
```

with a test that writes the same content twice, once CRLF and once LF, and
asserts the digests match.

- [ ] **Step 8: Commit**

```bash
git add src/center_kb/models.py src/center_kb/federation.py src/center_kb/doctor.py src/center_kb/cli.py tests/test_doctor_checks.py
git commit -m "feat(doctor): store and verify per-snapshot content digests on the hub (M9)"
```

---

### Task 7: `kb diff` reports titles and ordering, and the README stops contradicting it

**Files:**
- Modify: `src/center_kb/diff.py:90-131` (`diff_doc`), `:134-160`
  (`render_diff`), plus `SectionChange`/`DiffReport` near the top of the file
- Modify: `README.md:475`
- Test: `tests/test_diff.py`

**Interfaces:**
- Produces: `SectionChange.title_changed: bool = False`;
  `DiffReport.order_changed: bool = False`. `DiffReport.has_changes` must
  account for `order_changed`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_diff.py  (append — reuse this file's existing fixture that
# builds a git worktree with a committed manifest; mirror the setup of
# test_prose_changed_when_l2_edited at :69)
def test_title_change_in_the_manifest_only_is_reported(diff_repo):
    root, rev, doc_dir = diff_repo
    manifest = doc_dir / "_manifest.yaml"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(
        text.replace("title: Objective", "title: Objective and scope"),
        encoding="utf-8",
        newline="\n",
    )

    report = diff.diff_doc(root, "icao-annex-3", rev)

    assert [c.section_id for c in report.changed] == ["2.1"]
    assert report.changed[0].title_changed is True
    assert "(title)" in diff.render_diff(report)


def test_manifest_reorder_is_reported_once(diff_repo):
    root, rev, doc_dir = diff_repo
    manifest = doc_dir / "_manifest.yaml"
    m = models.Manifest.model_validate(
        yaml.safe_load(manifest.read_text(encoding="utf-8"))
    )
    m.sections.reverse()
    models.save_yaml_model(manifest, m)

    report = diff.diff_doc(root, "icao-annex-3", rev)

    assert report.order_changed is True
    assert report.has_changes is True
    assert "section order changed" in diff.render_diff(report)


def test_renumber_stays_add_plus_remove(diff_repo):
    """A section id is the citation key — an SME must see the old one go."""
    root, rev, doc_dir = diff_repo
    manifest = doc_dir / "_manifest.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("id: '2.1'", "id: '2.4'"),
        encoding="utf-8",
        newline="\n",
    )

    report = diff.diff_doc(root, "icao-annex-3", rev)

    assert [c.section_id for c in report.added] == ["2.4"]
    assert [c.section_id for c in report.removed] == ["2.1"]
    assert report.changed == []
```

If `tests/test_diff.py` has no shared `diff_repo` fixture, extract one from
the existing `test_prose_changed_when_l2_edited` (`:69`) setup and have both
use it — do not duplicate the git scaffolding.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/pytest tests/test_diff.py -k "title_change or reorder or renumber" -v`

Expected: the first two FAIL (`AttributeError: title_changed` / `no changes`);
the third already passes and locks today's behaviour in.

- [ ] **Step 3: Extend the dataclasses**

```python
@dataclass
class SectionChange:
    ...
    title_changed: bool = False
```

```python
@dataclass
class DiffReport:
    ...
    order_changed: bool = False

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed or self.order_changed)
```

(adjust to the file's actual field order and existing `has_changes` body —
keep every current field.)

- [ ] **Step 4: Compare titles and ordering in `diff_doc`**

Inside the `for sec in new.sections:` loop, next to `summary_changed`:

```python
        title_changed = old_sec.title.strip() != sec.title.strip()
```

add it to the `if` and to the `SectionChange(...)` construction:

```python
        if summary_changed or title_changed or prose_changed or content_changed:
            report.changed.append(
                SectionChange(
                    sec.id,
                    sec.title,
                    summary_changed=summary_changed,
                    title_changed=title_changed,
                    prose_changed=prose_changed,
                    content_changed=content_changed,
                    **_reviewed_fields(sec),
                )
            )
```

After the loop, before `return report`:

```python
    # Order, restricted to ids present on both sides: an add or a remove
    # alone shifts the sequence without being a reorder, and reporting it as
    # one would fire on every amendment (M14).
    common = new_by_id.keys() & old_by_id.keys()
    report.order_changed = [s.id for s in new.sections if s.id in common] != [
        s.id for s in old.sections if s.id in common
    ]
```

- [ ] **Step 5: Render both**

In `render_diff`, add `title` to the kinds tuple in the documented order and
emit the order line after the changed sections:

```python
        kinds = [
            k
            for k, on in (
                ("title", c.title_changed),
                ("summary", c.summary_changed),
                ("prose", c.prose_changed),
                ("content", c.content_changed),
            )
            if on
        ]
```

```python
    if report.order_changed:
        lines.append("• section order changed")
```

- [ ] **Step 6: Fix the README**

`README.md:475` currently claims `kb diff` reports L1 summary and L3
original changes and that "An L2-only edit shows stale on resolve but not in
diff." Replace with:

```markdown
`kb resolve` / `kb doctor --context` detect that pinned L2 content moved
since a citation was taken; `kb diff` reports what changed between two revs
of a doc — section title and L1 summary, the L2 slice (`prose`), the L3
original (`content`), added and removed sections, and whether the manifest
order changed. A renumbered section shows as an add plus a remove, because
the id is the citation key.
```

- [ ] **Step 7: Run the tests**

Run: `.venv/Scripts/pytest tests/test_diff.py tests/test_cli_doctor_diff.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/center_kb/diff.py README.md tests/test_diff.py
git commit -m "feat(diff): report title changes and manifest reorders; fix the README (M14, H2)"
```

---

### Task 8: exit code 2 means citation stale only

**Files:**
- Modify: `src/center_kb/cli.py:149`, `:192`, `:205`, `:543`, `:1220`,
  `:1575`, `:1625`, `:1779` (`Exit(2)` → `Exit(1)`); leave `:2170` and
  `:2650`
- Modify: `README.md:473` (exit-code table)
- Test: `tests/test_init.py`, `tests/test_summarize_cli.py`,
  `tests/test_cli_usage.py`, `tests/test_cli_hub.py`

**Interfaces:**
- Produces: nothing new. Behaviour: usage errors exit 1.

- [ ] **Step 1: Update the tests first (they encode the old contract)**

Change the expectation at each of these sites from `2` to `1`:
`tests/test_init.py:200`, `:613`, `:909`, `:1865`; `tests/test_cli_hub.py:339`;
`tests/test_cli_usage.py:160`; `tests/test_summarize_cli.py:57`.

**Do not touch** `tests/test_cli_context.py:64`, `:147`,
`tests/test_cli_doctor_diff.py:64`, `tests/test_cli_mission.py:273`,
`tests/test_cli_ticket.py:266`, `tests/test_resolve.py:119`,
`tests/test_federation_e2e.py:121` or `tests/test_lintcore.py` — those are
stale-class 2s and must stay 2.

Add one test that pins the distinction:

```python
# tests/test_cli_hub.py  (append)
def test_publish_pr_and_direct_is_exit_1_not_the_stale_code(tmp_path):
    """M11: a CI script reading the README's 'exit 2 = citation stale' used
    to see a misconfigured publish as a stale citation."""
    kb = _child_kb(tmp_path)  # reuse this file's existing helper
    result = runner.invoke(
        app, ["publish", "--kb-dir", str(kb), "--pr", "--direct"]
    )
    assert result.exit_code == 1, result.output
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/pytest tests/test_init.py tests/test_cli_hub.py tests/test_cli_usage.py tests/test_summarize_cli.py -q`

Expected: FAIL — the edited assertions now disagree with the code.

- [ ] **Step 3: Flip the eight sites**

At each of `cli.py:149`, `:192`, `:205`, `:543`, `:1220`, `:1575`, `:1625`,
`:1779`, change `raise typer.Exit(2)` to `raise typer.Exit(1)`. Verify each
one is a usage/misconfiguration path before changing it (bad `--lang`,
`--pr` with `--direct`, mutually exclusive transcript args, and so on), and
leave `:2170` (`resolve`) and `:2650` (`doctor`) alone.

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/pytest tests/test_init.py tests/test_cli_hub.py tests/test_cli_usage.py tests/test_summarize_cli.py tests/test_cli_context.py tests/test_resolve.py tests/test_lintcore.py -q`

Expected: PASS — the flipped ones on the new code, the stale-class ones
unchanged.

- [ ] **Step 5: Document the contract**

Replace `README.md:473`'s exit-code line with:

```markdown
| Exit | Meaning |
| --- | --- |
| 0 | success |
| 1 | error — including a misconfiguration (bad flag combination, missing required setting) |
| 2 | citation stale — `kb resolve`, `kb doctor --context`, `kb ba lint --fail-on-stale` only |

Caveat: click emits 2 of its own accord for an unrecognised flag or a bad
parameter type. A CI script that must distinguish "stale" from "you called
me wrong" should check the command it ran, not only the code.
```

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/cli.py README.md tests/
git commit -m "fix(cli): usage errors exit 1 so exit 2 means citation stale (M11)"
```

---

### Task 9: the `/ui` cookie carries a signed session, not the token

**Files:**
- Modify: `src/center_kb/web/auth.py` (`COOKIE_NAME`, new helpers,
  `_authorized`), `src/center_kb/web/ui.py:209-234` (login),
  `:546-555` (routes), `src/center_kb/templates/web/base.html` (logout
  control)
- Test: `tests/test_web_session.py` (create)

**Interfaces:**
- Produces, in `center_kb.web.auth`:
  - `COOKIE_NAME = "center_kb_session"`
  - `SESSION_MAX_AGE = 43200`
  - `make_session(token: str, now: float | None = None) -> str`
  - `verify_session(value: str, token: str, now: float | None = None) -> bool`
  - `cookie_is_secure(request) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_session.py  (new file)
"""M4: the /ui cookie used to be the bearer token itself."""
import time

import pytest

from center_kb.web import auth

TOKEN = "s3cr3t-token-abcdefgh"


def test_session_round_trip():
    value = auth.make_session(TOKEN)
    assert auth.verify_session(value, TOKEN) is True


def test_session_value_is_not_the_token():
    assert TOKEN not in auth.make_session(TOKEN)


def test_expired_session_is_rejected():
    issued = time.time() - auth.SESSION_MAX_AGE - 1
    value = auth.make_session(TOKEN, now=issued)
    assert auth.verify_session(value, TOKEN) is False


def test_tampered_signature_is_rejected():
    value = auth.make_session(TOKEN)
    ts, _, sig = value.partition(".")
    assert auth.verify_session(f"{ts}.{'0' * len(sig)}", TOKEN) is False


def test_forged_timestamp_is_rejected():
    """Extending your own session must not work without the token."""
    value = auth.make_session(TOKEN)
    _, _, sig = value.partition(".")
    assert auth.verify_session(f"{time.time():.0f}.{sig}", TOKEN) is False


@pytest.mark.parametrize("value", ["", "no-dot", "abc.def", ".", "x.y.z"])
def test_malformed_cookie_is_rejected_without_raising(value):
    assert auth.verify_session(value, TOKEN) is False
```

Plus the route-level pair, in the same file, using the existing web test
client helper (`tests/test_web_ui.py` builds one via
`center_kb.web.app.create_app` + `starlette.testclient.TestClient` — reuse
that shape; do not invent a new fixture):

```python
def test_login_sets_an_httponly_capped_cookie_that_is_not_the_token(web_client):
    resp = web_client.post(
        "/ui/login", data={"token": TOKEN}, follow_redirects=False
    )
    cookie = resp.headers["set-cookie"]
    assert "center_kb_session=" in cookie
    assert TOKEN not in cookie
    assert "HttpOnly" in cookie
    assert "Max-Age=43200" in cookie


def test_logout_clears_the_cookie(web_client):
    web_client.post("/ui/login", data={"token": TOKEN}, follow_redirects=False)
    resp = web_client.post("/ui/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/ui/login"
    assert "center_kb_session=;" in resp.headers["set-cookie"].replace('""', "")


def test_a_raw_token_cookie_no_longer_authorises(web_client):
    web_client.cookies.set("center_kb_session", TOKEN)
    resp = web_client.get("/ui/docs", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/ui/login"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/pytest tests/test_web_session.py -v`

Expected: FAIL — `AttributeError: module 'center_kb.web.auth' has no
attribute 'make_session'`.

- [ ] **Step 3: Implement the helpers in `auth.py`**

```python
import hashlib
import time

COOKIE_NAME = "center_kb_session"
# 12 h: long enough for a working day, short enough that a cookie copied off
# a machine stops working without an operator having to rotate the token.
SESSION_MAX_AGE = 43200


def make_session(token: str, now: float | None = None) -> str:
    """`<issued-at>.<hmac_sha256(token, issued-at)>`.

    The cookie is derived from the token instead of being the token (M4):
    /api and /mcp accept the token, so a cookie that WAS the token made
    every browser session an admin-equivalent credential at rest. Stateless
    on purpose — a server-side store would add a second sweeper to bound
    and would log everyone out on restart.
    """
    issued = int(now if now is not None else time.time())
    sig = hmac.new(
        token.encode("utf-8"), str(issued).encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{issued}.{sig}"


def verify_session(value: str, token: str, now: float | None = None) -> bool:
    issued_raw, _, sig = value.partition(".")
    if not sig or not issued_raw.isdecimal():
        return False
    expected = hmac.new(
        token.encode("utf-8"), issued_raw.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    age = (now if now is not None else time.time()) - int(issued_raw)
    return 0 <= age <= SESSION_MAX_AGE
```

In `_authorized`, replace the cookie compare:

```python
        morsel = cookie.get(COOKIE_NAME)
        if morsel is None:
            return False
        try:
            return verify_session(morsel.value, self.token)
        except (TypeError, ValueError):
            return False
```

- [ ] **Step 4: Derive the `Secure` flag and set the cookie**

Still in `auth.py`:

```python
def cookie_is_secure(request, trusted_proxies: int = 0) -> bool:
    """https on the wire, or an X-Forwarded-Proto we are configured to
    believe. No CENTER_KB_HTTP_INSECURE_COOKIE knob: CENTER_KB_TRUSTED_PROXIES
    already declares whether a proxy in front is ours to trust, and a second
    flag for the same fact would let them disagree."""
    if request.url.scheme == "https":
        return True
    if trusted_proxies > 0:
        proto = request.headers.get("x-forwarded-proto", "")
        return proto.split(",")[0].strip().lower() == "https"
    return False
```

In `ui.py`'s `login_post`, replace the `set_cookie` call:

```python
        if hmac.compare_digest(submitted, token):
            resp = RedirectResponse("/ui", status_code=303)
            secure = cookie_is_secure(request, trusted_proxies)
            if not secure:
                logger.warning(
                    "session cookie set without Secure — request arrived over "
                    "plain HTTP. Behind a TLS proxy, set "
                    "CENTER_KB_TRUSTED_PROXIES to the number of proxies in "
                    "front so X-Forwarded-Proto is believed."
                )
            resp.set_cookie(
                COOKIE_NAME,
                make_session(token),
                httponly=True,
                samesite="lax",
                secure=secure,
                max_age=SESSION_MAX_AGE,
            )
            return resp
```

Extend the `center_kb.web.auth` import in `ui.py` with `SESSION_MAX_AGE`,
`cookie_is_secure` and `make_session`.

- [ ] **Step 5: Add the logout route**

In `ui.py`, next to `login_post`:

```python
    async def logout_post(request: Request) -> Response:
        resp = RedirectResponse("/ui/login", status_code=303)
        resp.delete_cookie(COOKIE_NAME, path="/")
        return resp
```

Register it in the returned route list, and add it to `auth.EXEMPT_PATHS`
so a user whose session already expired can still clear the cookie:

```python
        Route("/ui/logout", logout_post, methods=["POST"]),
```

In `templates/web/base.html`, add the control inside the existing header
nav — a form, not a link, so it is not triggered by a prefetch:

```html
<form method="post" action="/ui/logout" class="nav-logout">
  <button type="submit" class="seg">Sign out</button>
</form>
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/pytest tests/test_web_session.py tests/test_web_ui.py tests/test_web_app.py tests/test_ratelimit.py -q`

Expected: PASS. Existing tests that log in by setting a raw-token cookie
must be updated to post to `/ui/login` or to set
`auth.make_session(TOKEN)` — that is the intended breaking change.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/web/auth.py src/center_kb/web/ui.py src/center_kb/templates/web/base.html tests/test_web_session.py tests/
git commit -m "feat(web): signed expiring session cookie plus a logout route (M4)"
```

---

### Task 10: security headers on every response

**Files:**
- Create: `src/center_kb/web/headers.py`
- Modify: `src/center_kb/web/app.py:87-89` (wrap the app)
- Test: `tests/test_web_headers.py` (create)

**Interfaces:**
- Produces: `center_kb.web.headers.SecurityHeadersMiddleware(app)` — a raw
  ASGI middleware, same shape as `TokenAuthMiddleware`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_headers.py  (new file)
"""M5: no response carried a single security header."""
REQUIRED = {
    "content-security-policy",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
}


def test_headers_on_an_authorised_page(web_client_logged_in):
    resp = web_client_logged_in.get("/ui")
    assert REQUIRED <= set(resp.headers)


def test_headers_on_the_login_redirect(web_client):
    resp = web_client.get("/ui", follow_redirects=False)
    assert resp.status_code == 302
    assert REQUIRED <= set(resp.headers)


def test_headers_on_a_401(web_client):
    resp = web_client.get("/api/docs")
    assert resp.status_code == 401
    assert REQUIRED <= set(resp.headers)


def test_csp_allows_the_one_external_script_and_inline_styles(web_client_logged_in):
    csp = web_client_logged_in.get("/ui").headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "frame-ancestors 'none'" in csp


def test_hsts_only_over_https(web_client, web_client_https):
    assert "strict-transport-security" not in web_client.get(
        "/ui", follow_redirects=False
    ).headers
    assert "strict-transport-security" in web_client_https.get(
        "/ui", follow_redirects=False
    ).headers
```

`web_client_https` is a `TestClient(app, base_url="https://testserver")`.
Put the three client fixtures in `tests/conftest.py` if it has one, else at
the top of this file, and reuse them from Tasks 11-13.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/pytest tests/test_web_headers.py -v`

Expected: FAIL — no such headers exist anywhere in `src/`.

- [ ] **Step 3: Write the middleware**

```python
# src/center_kb/web/headers.py
"""Security response headers for every path, including redirects and errors.

Outside TokenAuthMiddleware on purpose: its 302 to /ui/login and its 401/429
JSON are responses too, and a header policy with holes at the auth boundary
is the wrong shape. Defence in depth — the escaping in mdrender/Jinja is
what actually stops XSS today; this is what limits the damage if that ever
regresses.
"""
from __future__ import annotations

# style-src allows 'unsafe-inline': the templates carry ~30 inline style=
# attributes plus three <noscript><style> blocks. script-src does NOT —
# that is the directive that matters, and the UI has exactly one external
# script (/ui/static/app.js) and zero inline script.
CSP = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self'",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    )
)

STATIC_HEADERS = (
    (b"content-security-policy", CSP.encode("ascii")),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
)
HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


class SecurityHeadersMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # HSTS only over https: pinning a plain-HTTP dev host for a year is a
        # foot-gun, and a browser ignores the header on http anyway.
        extra = list(STATIC_HEADERS)
        if scope.get("scheme") == "https":
            extra.append(HSTS)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + [
                    (k, v) for k, v in extra if k not in present
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)
```

- [ ] **Step 4: Wire it in**

`app.py`, final lines of `create_app`:

```python
    app = Starlette(routes=routes, lifespan=lifespan)
    return SecurityHeadersMiddleware(TokenAuthMiddleware(app, token))
```

with `from center_kb.web.headers import SecurityHeadersMiddleware` at the
top.

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/pytest tests/test_web_headers.py tests/test_web_ui.py tests/test_web_api.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/web/headers.py src/center_kb/web/app.py tests/test_web_headers.py
git commit -m "feat(web): security headers on every response (M5)"
```

---

### Task 11: one rate-limit bucket for failed shared-secret attempts

The login limiter is bypassed entirely by sending the same secret in an
`Authorization` header: 10 unauthenticated `/api/docs` hits returned
`401` ten times, never `429`.

**Files:**
- Modify: `src/center_kb/web/auth.py` (`TokenAuthMiddleware.__init__`,
  `__call__`), `src/center_kb/web/app.py` (build and inject the limiter),
  `src/center_kb/web/ui.py:197-207` (accept injected `trusted_proxies`)
- Test: `tests/test_web_auth_ratelimit.py` (create)

**Interfaces:**
- Consumes: `ratelimit.SlidingWindowLimiter`, `ratelimit.client_key`,
  `ratelimit.trusted_proxies_from_env` (all exist).
- Produces: `TokenAuthMiddleware(app, token, limiter=None,
  trusted_proxies=0)`; `ui.build_routes(config, token, store_factory=None,
  login_limiter=None, trusted_proxies=None)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_auth_ratelimit.py  (new file)
"""M6: the same secret over Authorization had no lockout at all."""
from center_kb.web.ratelimit import LOGIN_MAX_ATTEMPTS


def test_failed_header_auth_is_eventually_429(web_client):
    codes = [
        web_client.get(
            "/api/docs", headers={"Authorization": "Bearer wrong"}
        ).status_code
        for _ in range(LOGIN_MAX_ATTEMPTS + 3)
    ]
    assert codes[:LOGIN_MAX_ATTEMPTS] == [401] * LOGIN_MAX_ATTEMPTS
    assert codes[-1] == 429


def test_successful_auth_never_counts(web_client, token):
    for _ in range(LOGIN_MAX_ATTEMPTS + 5):
        assert web_client.get(
            "/api/docs", headers={"Authorization": f"Bearer {token}"}
        ).status_code == 200


def test_the_header_path_and_the_login_form_share_one_bucket(web_client):
    """Spending attempts on the header must lock the form — otherwise the
    limiter is decoration."""
    for _ in range(LOGIN_MAX_ATTEMPTS):
        web_client.get("/api/docs", headers={"Authorization": "Bearer wrong"})
    resp = web_client.post(
        "/ui/login", data={"token": "wrong"}, follow_redirects=False
    )
    assert resp.status_code == 429


def test_browser_paths_get_html_and_api_paths_get_json(web_client):
    for _ in range(LOGIN_MAX_ATTEMPTS + 1):
        web_client.get("/api/docs", headers={"Authorization": "Bearer wrong"})
    api_resp = web_client.get("/api/docs", headers={"Authorization": "Bearer wrong"})
    ui_resp = web_client.get("/ui/docs", follow_redirects=False)
    assert api_resp.status_code == 429
    assert api_resp.headers["content-type"].startswith("application/json")
    assert ui_resp.status_code == 429
    assert ui_resp.headers["content-type"].startswith("text/html")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/pytest tests/test_web_auth_ratelimit.py -v`

Expected: FAIL — every code is 401; no 429 ever appears.

- [ ] **Step 3: Teach the middleware to count failures**

`auth.py`:

```python
class TokenAuthMiddleware:
    def __init__(self, app, token: str, limiter=None, trusted_proxies: int = 0) -> None:
        self.app = app
        self.token = token
        # The SAME limiter instance the login form uses (app.py builds one and
        # injects it into both). Separate buckets would leave the bypass M6
        # describes open in the other direction: spend on the header, retry on
        # the form.
        self.limiter = limiter
        self.trusted_proxies = trusted_proxies
```

In `__call__`, after the exempt/authorised early return and before the
302/401 branches:

```python
        from starlette.requests import Request

        from center_kb.web.ratelimit import client_key

        # Request(scope) with no receive is enough for headers + client; we
        # never read the body here. Reuses client_key so the header path and
        # the login form agree on what a client IS, trusted-proxy hops
        # included.
        key = client_key(Request(scope), self.trusted_proxies)
        limited = self.limiter is not None and not self.limiter.allow(key)
        if limited:
            logger.warning("auth rate-limited for %s on %s", key, path)
            if path == "/" or path.startswith("/ui"):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 429,
                        "headers": [(b"content-type", b"text/html; charset=utf-8")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b"<h1>Too many attempts</h1><p>Try again later.</p>",
                    }
                )
                return
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {"type": "http.response.body", "body": b'{"error": "too many attempts"}'}
            )
            return
```

Only failed auth reaches this code — the authorised path returned above, so
legitimate traffic never touches the limiter.

- [ ] **Step 4: Build one limiter in `app.py` and inject it twice**

```python
    from center_kb.web.ratelimit import (
        LOGIN_MAX_ATTEMPTS,
        LOGIN_WINDOW_SECONDS,
        SlidingWindowLimiter,
        trusted_proxies_from_env,
    )

    # One bucket for "a failed attempt at the shared secret", wherever it
    # arrives (M6). Read once here rather than inside build_routes, so the
    # middleware and the login form cannot disagree about the proxy count.
    trusted_proxies = trusted_proxies_from_env()
    auth_limiter = SlidingWindowLimiter(LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS)
```

and:

```python
    routes += ui.build_routes(
        config, token, login_limiter=auth_limiter, trusted_proxies=trusted_proxies
    )
```

```python
    return SecurityHeadersMiddleware(
        TokenAuthMiddleware(
            app, token, limiter=auth_limiter, trusted_proxies=trusted_proxies
        )
    )
```

In `ui.build_routes`, accept the new parameter and fall back to the env read
only when it is not supplied (keeps direct unit callers working):

```python
def build_routes(
    config: ServerConfig,
    token: str,
    store_factory=None,
    login_limiter=None,
    trusted_proxies: int | None = None,
) -> list[Route]:
    limiter = login_limiter or SlidingWindowLimiter(
        LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS
    )
    if trusted_proxies is None:
        trusted_proxies = trusted_proxies_from_env()
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/pytest tests/test_web_auth_ratelimit.py tests/test_web_app.py tests/test_web_ui.py tests/test_web_api.py -q`

Expected: PASS. Any existing test that makes more than
`LOGIN_MAX_ATTEMPTS` unauthenticated requests in one window now sees 429 —
give those their own limiter instance or their own client.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/web/auth.py src/center_kb/web/app.py src/center_kb/web/ui.py tests/test_web_auth_ratelimit.py
git commit -m "fix(web): rate-limit failed header auth in the same bucket as login (M6)"
```

---

### Task 12: a corrupt snapshot renders an error, not a bare 500

**Files:**
- Modify: `src/center_kb/web/api.py:88-106` (`load_manifest`),
  `src/center_kb/web/app.py` (exception handler)
- Test: `tests/test_web_snapshot_errors.py` (create)

**Interfaces:**
- Produces: `center_kb.web.api.SnapshotCorruptError(doc_id: str, detail:
  str)` with `.doc_id` and `.detail`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_snapshot_errors.py  (new file)
"""M8: a corrupt federation manifest took the doc routes down with a 500."""


def _corrupt_a_manifest(hub_dir):
    manifest = next((hub_dir / "federation").rglob("_manifest.yaml"))
    manifest.write_text("id: [unclosed\n", encoding="utf-8", newline="\n")
    return manifest.parent.name


def test_api_doc_detail_is_503_json_not_500(web_client_logged_in, hub_dir):
    doc_id = _corrupt_a_manifest(hub_dir)
    resp = web_client_logged_in.get(f"/api/docs/{doc_id}")
    assert resp.status_code == 503
    assert resp.json()["error"]


def test_ui_doc_page_renders_the_shell_not_a_bare_500(web_client_logged_in, hub_dir):
    doc_id = _corrupt_a_manifest(hub_dir)
    resp = web_client_logged_in.get(f"/ui/docs/{doc_id}")
    assert resp.status_code == 503
    assert "Internal Server Error" not in resp.text
    assert "CENTER-KB" in resp.text  # the shell rendered


def test_ui_home_still_degrades_to_200(web_client_logged_in, hub_dir):
    _corrupt_a_manifest(hub_dir)
    assert web_client_logged_in.get("/ui").status_code == 200
```

`hub_dir` is whatever fixture the existing web tests use to build a
published hub — reuse it.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/pytest tests/test_web_snapshot_errors.py -v`

Expected: FAIL — the two doc routes raise, and `TestClient` either
propagates the exception or returns a bare 500.

- [ ] **Step 3: Raise a domain error from `load_manifest`**

`api.py`:

```python
class SnapshotCorruptError(Exception):
    """A published snapshot's _manifest.yaml does not parse or validate.

    uidata._iter_manifests survives this (the doc simply does not list), so
    /ui keeps working — but the doc routes used to propagate it into a bare
    500 with no shell (M8).
    """

    def __init__(self, doc_id: str, detail: str) -> None:
        super().__init__(f"{doc_id}: {detail}")
        self.doc_id = doc_id
        self.detail = detail
```

```python
    try:
        manifest = models.load_yaml_model(
            r.kb_dir / doc_id / "_manifest.yaml", models.Manifest
        )
    except (yaml.YAMLError, ValidationError, ValueError) as exc:
        raise SnapshotCorruptError(doc_id, " ".join(str(exc).split())) from exc
```

with `import yaml` and `from pydantic import ValidationError` at the top if
absent.

- [ ] **Step 4: Register one handler for both surfaces**

`app.py`, before constructing `Starlette`:

```python
    async def snapshot_corrupt(request: Request, exc: api.SnapshotCorruptError):
        logger.warning("corrupt published snapshot: %s", exc)
        if request.url.path.startswith("/api"):
            return JSONResponse(
                {
                    "error": "snapshot_corrupt",
                    "detail": f"published snapshot for '{exc.doc_id}' is corrupt",
                },
                status_code=503,
            )
        return ui.render_error_page(
            config,
            status=503,
            title="Document unavailable",
            detail=f"The published snapshot for '{exc.doc_id}' is corrupt. "
            "Re-publish it from the owning repo.",
        )

    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        exception_handlers={api.SnapshotCorruptError: snapshot_corrupt},
    )
```

`ui.render_error_page(config, *, status, title, detail) -> HTMLResponse` is
new: factor it out of whatever `ui.py` already uses for its 404 path so the
shell markup is not duplicated, and have the 404 path call it too. `logger`
already exists in `app.py`'s intake branch — hoist that
`logging.getLogger("center_kb.web.app")` to module scope.

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/pytest tests/test_web_snapshot_errors.py tests/test_web_ui.py tests/test_web_api.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/web/api.py src/center_kb/web/app.py src/center_kb/web/ui.py tests/test_web_snapshot_errors.py
git commit -m "fix(web): corrupt snapshots render an error page instead of a bare 500 (M8)"
```

---

### Task 13: login body cap, no-store, health trim, `_sweep` test

Three items the review missed plus two LOWs, all small and all in the same
surface.

**Files:**
- Modify: `src/center_kb/web/ui.py:209-234` (cap + `no-store`),
  `src/center_kb/web/api.py:109-116` (health),
  `src/center_kb/web/auth.py` (`is_authorized_request`)
- Test: `tests/test_web_session.py`, `tests/test_web_app.py`

**Interfaces:**
- Produces: `auth.is_authorized_request(request, token) -> bool` — a
  `Request`-level view of the same check `TokenAuthMiddleware._authorized`
  does on a scope.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_session.py  (append)
def test_login_rejects_an_oversized_body(web_client):
    resp = web_client.post(
        "/ui/login", data={"token": "x" * (64 * 1024)}, follow_redirects=False
    )
    assert resp.status_code == 413


def test_login_pages_are_not_cacheable(web_client):
    assert web_client.get("/ui/login").headers["cache-control"] == "no-store"
    assert (
        web_client.post(
            "/ui/login", data={"token": "wrong"}, follow_redirects=False
        ).headers["cache-control"]
        == "no-store"
    )


def test_health_is_minimal_without_auth_and_detailed_with_it(web_client, token):
    anon = web_client.get("/api/health").json()
    assert anon == {"status": "ok"}
    authed = web_client.get(
        "/api/health", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert "hub_configured" in authed and "hub_reachable" in authed
```

```python
# tests/test_web_app.py  (append — L23)
def test_sweep_drops_expired_keys(monkeypatch):
    from center_kb.web import ratelimit

    monkeypatch.setattr(ratelimit, "_SWEEP_THRESHOLD", 2)
    clock = [1000.0]
    limiter = ratelimit.SlidingWindowLimiter(5, 60.0, clock=lambda: clock[0])
    for i in range(3):
        limiter.allow(f"ip-{i}")
    assert len(limiter._hits) == 3

    clock[0] += 61.0
    limiter.allow("ip-new")

    assert set(limiter._hits) == {"ip-new"}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/pytest tests/test_web_session.py -k "oversized or cacheable or health" tests/test_web_app.py -k sweep -v`

Expected: FAIL — 200 instead of 413, no `cache-control`, hub fields exposed
anonymously, and `_hits` still holds three keys.

- [ ] **Step 3: Cap the login body**

In `login_post`, before `await request.form()`:

```python
        # /ui/login is unauthenticated and auth-exempt, and Starlette applies
        # no size limit to a form body — the same reason intake_routes caps
        # every upload (intake_routes.read_capped).
        if int(request.headers.get("content-length") or 0) > LOGIN_MAX_BODY:
            return HTMLResponse("body too large", status_code=413)
```

with `LOGIN_MAX_BODY = 8 * 1024` as a module constant in `ui.py` (a token is
tens of bytes; 8 KiB is generous). A chunked request without
`content-length` still reaches `request.form()`; Starlette's own
`max_part_size` governs there, and the token field is not a file part.

- [ ] **Step 4: Add `no-store` to both login responses**

Give every `HTMLResponse`/`RedirectResponse` returned from `login_get` and
`login_post` `headers={"Cache-Control": "no-store"}` — including the 429
and 413 paths.

- [ ] **Step 5: Trim `/api/health`**

`auth.py`:

```python
def is_authorized_request(request, token: str) -> bool:
    """The Request-level twin of TokenAuthMiddleware._authorized — for the
    handful of exempt routes that want to vary their output by auth."""
    auth_header = request.headers.get("authorization", "")
    try:
        if hmac.compare_digest(auth_header, f"Bearer {token}"):
            return True
    except TypeError:
        return False
    return verify_session(request.cookies.get(COOKIE_NAME, ""), token)
```

`api.py`'s health handler — note `build_routes(config)` has no token today,
so thread it through from `app.py` (`api.build_routes(config, token)`):

```python
    async def health(request: Request) -> JSONResponse:
        # Unauthenticated callers get liveness only. hub_configured /
        # hub_reachable describe the deployment, and this route is
        # deliberately auth-exempt for probes (L22).
        if not is_authorized_request(request, token):
            return JSONResponse({"status": "ok"})
        return JSONResponse(
            {
                "status": "ok",
                "hub_configured": bool(config.hub),
                "hub_reachable": hub_handle(config) is not None,
            }
        )
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/pytest tests/test_web_session.py tests/test_web_app.py tests/test_web_api.py tests/test_web_ui.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/web/ui.py src/center_kb/web/api.py src/center_kb/web/auth.py src/center_kb/web/app.py tests/
git commit -m "fix(web): cap the login body, no-store on login, minimal anonymous health, test _sweep (L22, L23)"
```

---

### Task 14: `tokens` describes what the response actually carries

`query.py:356-357` sets `tokens = count_tokens(content) +
count_tokens(snippet)` — correct for budget accounting, and MCP and the CLI
both return the snippet. REST and the UI count it and never return it.

**Files:**
- Modify: `src/center_kb/query.py:346-378` (`QueryResult` construction and
  the dataclass), `src/center_kb/web/api.py:203-213`,
  `src/center_kb/web/ui.py:260-280`, `src/center_kb/cli.py:1383-1430`
  (`query`), `:1440-1465` (`get`)
- Test: `tests/test_web_api.py`, `tests/test_query.py`, `tests/test_cli_query.py`

**Interfaces:**
- Produces: `QueryResult.content_tokens: int` — tokens of `content` alone.
  `tokens` keeps its meaning (budget accounting) and its value.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_api.py  (append)
def test_api_search_tokens_describe_the_returned_text(web_client_logged_in):
    from center_kb.mdutils import count_tokens

    body = web_client_logged_in.get("/api/search?q=meteorological").json()
    assert body["results"], body
    for r in body["results"]:
        assert r["tokens"] == count_tokens(r["content"])
```

```python
# tests/test_query.py  (append)
def test_budget_tokens_still_include_the_snippet(hub):
    from center_kb.query import search

    results = search(hub, "meteorological", budget=8000)
    assert results
    for r in results:
        assert r.tokens >= r.content_tokens
```

Plus the stale-note pair:

```python
# tests/test_cli_query.py  (append)
def test_query_warns_when_the_hub_cache_is_stale(monkeypatch, stale_hub_kb):
    result = runner.invoke(app, ["query", "meteorological", "--kb-dir", str(stale_hub_kb)])
    assert "hub cache is stale" in result.output
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/pytest tests/test_web_api.py -k tokens_describe tests/test_query.py -k budget_tokens -v`

Expected: FAIL — `AttributeError: content_tokens`, and the REST number is
larger than the returned content whenever a snippet exists.

- [ ] **Step 3: Add the field**

`query.py`, on `QueryResult`:

```python
    # tokens = what this result SPENT of the budget (content + snippet).
    # content_tokens = what a caller that does not receive the snippet
    # actually got — REST and the web UI report this one, so their number
    # stops describing text they never send (M17).
    content_tokens: int = 0
```

and at the construction site:

```python
        content_tokens = count_tokens(content)
        n_tokens = content_tokens + (count_tokens(snippet) if snippet else 0)
```

```python
                tokens=n_tokens,
                content_tokens=content_tokens,
```

- [ ] **Step 4: Report it on the two surfaces that drop the snippet**

`api.py`'s `api_search` result dict: `"tokens": r.content_tokens,`.
`ui.py`'s `_search_screen` result dict: same substitution wherever
`r.tokens` feeds the rendered token figure.

- [ ] **Step 5: Share the stale-hub note**

`mcp.py:148-153` has `_stale_note(hub)`. Move it to `query.py` as a public
`stale_hub_note(hub) -> str` (identical body), have `mcp.py` call that, and
use it in:

- `cli.py`'s `query` and `get`: `typer.secho(stale_hub_note(handle).strip(),
  fg=typer.colors.YELLOW, err=True)` when non-empty.
- `api.py`'s `api_search`: add `"notes": [stale_hub_note(hub)]` when
  non-empty, alongside `results`.

`_hub_or_exit` already prints a `[warn] hub cache is stale` line for CLI
commands — if that covers `query`/`get` in practice, assert on the existing
line in the test instead of adding a second one. Check before duplicating.

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/pytest tests/test_query.py tests/test_web_api.py tests/test_web_ui.py tests/test_cli_query.py tests/test_mcp.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/query.py src/center_kb/web/api.py src/center_kb/web/ui.py src/center_kb/cli.py src/center_kb/mcp.py tests/
git commit -m "fix(search): REST/UI tokens count only returned text; share the stale-hub note (M17)"
```

---

### Task 15: the newline trip-wire scans instead of listing

`COMMITTED_WRITERS` is a hardcoded six-module list; three other modules
write committed content and are not in it (they happen to be correct today).

**Files:**
- Modify: `tests/test_windows_hygiene.py:31-60`
- Modify: source files that need an exemption comment (`hub.py:154`,
  `intake.py:1330`, `ingest/parser.py:129`, `web/ui.py:517`, plus whatever
  the scan reports)

**Interfaces:**
- Produces: the convention `# newline-exempt: <reason>` on a write-mode call
  that deliberately does not pass `newline="\n"`.

- [ ] **Step 1: Write the failing test**

Replace `COMMITTED_WRITERS` and `test_committed_writers_force_lf_newline`
with:

```python
import ast

# Inverted from a hardcoded module list (M16): the old version guarded six
# files, and svcnote.py / codeingest/core.py / usage/ledger.py wrote
# committed content outside it. A scan cannot drift — a new writer fails
# until someone states, at the call site, why it is exempt.
EXEMPT_MARKER = "newline-exempt:"


def _write_calls(tree: ast.AST) -> list[ast.Call]:
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name == "write_text":
            out.append(node)
        elif name == "open":
            mode = ""
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                mode = str(node.args[1].value)
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = str(kw.value.value)
            if any(c in mode for c in "wax"):
                out.append(node)
    return out


def test_every_text_writer_forces_lf_or_says_why_not():
    offenders = []
    for py in sorted(SRC.rglob("*.py")):
        text = py.read_text(encoding="utf-8")
        lines = text.splitlines()
        tree = ast.parse(text)
        for call in _write_calls(tree):
            kwargs = {kw.arg for kw in call.keywords}
            if "newline" in kwargs:
                continue
            if "b" in "".join(
                str(a.value) for a in call.args[1:2]
                if isinstance(a, ast.Constant)
            ):
                continue  # binary mode has no newline translation
            window = "\n".join(
                lines[max(0, call.lineno - 3): call.end_lineno or call.lineno]
            )
            if EXEMPT_MARKER in window:
                continue
            offenders.append(f"{py.relative_to(SRC)}:{call.lineno}")
    assert not offenders, (
        "text writers without newline=\"\\n\" and without a "
        f"'# {EXEMPT_MARKER} <reason>' comment: {offenders} — CRLF from a "
        "Windows machine churns hub diffs and skews content digests"
    )
```

- [ ] **Step 2: Run it to see the real offender list**

Run: `.venv/Scripts/pytest tests/test_windows_hygiene.py -v`

Expected: FAIL, listing every write-mode call with neither the kwarg nor a
marker. That list is the work for Step 3 — read it before editing anything.

- [ ] **Step 3: Resolve each offender**

For each: if it writes committed KB content, add `newline="\n"`. If it is
local-only, binary, or a cache, add the marker above the call, e.g.:

```python
    # newline-exempt: local marker file, never committed or digested
    (root / ".kb-cache-marker").write_text(stamp, encoding="utf-8")
```

Do not add the marker to anything that lands under `.kb/` or `federation/`.

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/Scripts/pytest tests/test_windows_hygiene.py -v`

Expected: PASS.

- [ ] **Step 5: Prove the scan actually catches a regression**

Temporarily add `(tmp / "x.md").write_text("y", encoding="utf-8")` to a
module under `src/center_kb/`, re-run, confirm it FAILS naming that line,
then remove it.

- [ ] **Step 6: Commit**

```bash
git add tests/test_windows_hygiene.py src/center_kb/
git commit -m "test(windows): scan every text writer instead of a hardcoded list (M16)"
```

---

### Task 16: ruff select that carries signal

`pyproject.toml` sets only `per-file-ignores`, so only `E4/E7/E9/F` run and
all 11 `# noqa: BLE001` markers in `src/` are inert.

**Files:**
- Modify: `pyproject.toml:76-78`
- Modify: whatever `src/` files the triage requires

**Interfaces:** none.

- [ ] **Step 1: Add the config**

```toml
[tool.ruff.lint]
# Default is E4/E7/E9/F only, which made "ruff check passed" mean very
# little: the 11 `# noqa: BLE001` markers in src/ were inert because BLE
# was never enabled, and RUF100 was not there to say so. B/I/UP/SIM are
# deliberately NOT here yet — 198 mechanical edits belong in their own PR.
select = ["E4", "E7", "E9", "F", "BLE", "RUF100", "S"]

[tool.ruff.lint.per-file-ignores]
# pytest.importorskip must run before the guarded import
"tests/*" = ["E402", "S101"]
```

- [ ] **Step 2: Run ruff to get the real list**

Run: `.venv/Scripts/ruff check src tests --statistics`

Expected: FAIL. Around 32 `BLE001`, 37 `RUF100`, and roughly 110 `S` hits of
which ~75 are `S603`/`S607` at the git/subprocess wrappers.

- [ ] **Step 3: Ignore the two subprocess families where they belong**

Add to `per-file-ignores`, one line per module with a stated reason — and
only for modules that shell out to git/docker by design:

```toml
# S603/S607: every subprocess call here is a fixed git/docker argv built in
# code, never a shell string and never user-interpolated; gitio is the single
# chokepoint that guarantees it.
"src/center_kb/gitio.py" = ["S603", "S607"]
```

Repeat for the other modules ruff names (`intake.py`, `dockersetup.py`,
`llm.py`, `cipublish.py`, `scripts/*` if they are linted). Do not add a
blanket `src/*` ignore.

- [ ] **Step 4: Triage the remaining ~28 one by one**

Re-run `.venv/Scripts/ruff check src tests`. For each hit:

- `S105`/`S106` (hardcoded password): if it is a test fixture token, it is
  under `tests/` and already ignored; in `src/` it is a real finding —
  check whether it is a default token or an env-var name, and fix or
  `# noqa: S105` with the reason.
- `S324` (insecure hash): if a sha1/md5 is used as a content *identifier*
  rather than a security primitive, pass `usedforsecurity=False` (Python
  3.9+) — that is the documented, lint-clean way to say so.
- `S310` (url open): confirm the scheme is validated before the call; add
  the validation if not.
- `S608` (SQL string): confirm no user value is interpolated — the search
  path builds FTS queries; parameterise anything that is not a fixed
  fragment.
- `BLE001` (blind except): narrow the clause if the real exception set is
  known; otherwise keep the existing `# noqa: BLE001` — it is now live and
  meaningful.

Every `noqa` you keep or add must name a reason on the same line.

- [ ] **Step 5: Verify clean, and that RUF100 keeps it honest**

Run: `.venv/Scripts/ruff check src tests && .venv/Scripts/pytest tests/test_windows_hygiene.py -q`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/center_kb/
git commit -m "chore(lint): enable BLE, RUF100 and S in ruff and triage the findings (L28)"
```

---

### Task 17: docs that currently mislead, and the two tooling leftovers

**Files:**
- Modify: `src/center_kb/cli.py:1390`, `:1447`, `:2033`, `:2058`, `:2087`,
  `:2180`, `:2323`, `:2567` (`--hub` help), `src/center_kb/hub.py:159-161`
  (docstring), `src/center_kb/cipublish.py:77`, `:113`, `:152`, `:158`,
  `:160`, `:181` (`print`), `scripts/gate.sh:37` (hint)
- Modify: `docs/deploy-remote-mcp.md:6-10`
- Test: `tests/test_check_package.py`

**Interfaces:** none.

- [ ] **Step 1: Write the failing test for `installed_version`**

```python
# tests/test_check_package.py  (append — M15 leftover)
import os
import stat
import sys
from pathlib import Path

from scripts.check_package import installed_version, venv_bin


def test_installed_version_reads_the_venv_entry_point(tmp_path):
    """The one helper venv_bin exists for, and the only one still untested."""
    venv = tmp_path / "v"
    bindir = venv / venv_bin(venv).name
    bindir.mkdir(parents=True)
    if os.name == "nt":
        (bindir / "kb.bat").write_text(
            "@echo kb, version 9.9.9\n", encoding="utf-8", newline="\r\n"
        )
    else:
        stub = bindir / "kb"
        stub.write_text('#!/bin/sh\necho "kb, version 9.9.9"\n', encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    assert installed_version(venv) == "9.9.9"
```

Match the real `installed_version` return shape first — if it returns the
whole `kb --version` line rather than a bare version, assert on that
instead. Read `scripts/check_package.py:114-121` before writing the
assertion.

- [ ] **Step 2: Run it**

Run: `.venv/Scripts/pytest tests/test_check_package.py -k installed_version -v`

Expected: FAIL on Windows if the helper still cannot find a `.bat`/`.exe`
stub; PASS immediately if `venv_bin` plus the stub already satisfy it — in
which case the finding is closed and the test is the regression guard.

- [ ] **Step 3: Fix the help text and the docstring**

At the eight `cli.py` sites, `"kb-hub URL/path (empty = don't use)"` →
`"kb-hub URL/path (empty = config)"`, matching `assets` at `:1951`/`:1994`.
The hub is mandatory (C7); "don't use" describes behaviour that no longer
exists.

`hub.py:159-161`: replace the "the hub is an enhancement, not a hard
requirement" sentence with:

```python
    """... None = the hub is unreachable and there is no cache yet. Every
    caller treats that as fatal — CLI commands exit 1 via _hub_or_exit and
    the web layer serves 503 — since the 2026-07-13 hub-first change. Do not
    read None as "continue with the local KB".
    """
```

- [ ] **Step 4: Replace the bare prints**

At the six `cipublish.py` sites, `print(x)` → `typer.echo(x)` (add
`import typer`). If any is a diagnostic rather than user-facing output, use
`logger.info` instead and say which in the commit body.

- [ ] **Step 5: Fix the gate hint and the deploy doc**

`scripts/gate.sh:37` — make the hint match the platform:

```bash
  if [ -d .venv/Scripts ]; then
    echo "  .venv/Scripts/pip install -e '.[dev]'" >&2
  else
    echo "  .venv/bin/pip install -e '.[dev]'" >&2
  fi
```

`docs/deploy-remote-mcp.md:6-10` — delete the stale advisory note (the tool
now forces `core.autocrlf=false` and `core.eol=lf` in `gitio.clone`, and
`kb init` ships `.gitattributes`) and replace it with:

```markdown
Line endings need no operator action: `gitio.clone` forces
`core.autocrlf=false` / `core.eol=lf` and writes them into every hub cache
clone, and `kb init` scaffolds `.gitattributes` (`federation/** -text` on a
hub, `.kb/** -text` on a child).

Behind a TLS-terminating reverse proxy, set
`CENTER_KB_TRUSTED_PROXIES=<number of proxies>`. It does two things: the
rate limiter keys on the real client instead of collapsing every user into
the proxy's bucket, and the `/ui` session cookie earns its `Secure` flag
from `X-Forwarded-Proto`. Left unset behind a proxy, the server logs a
warning and sets the cookie without `Secure`. The proxy must *overwrite*
`X-Forwarded-For`, not append to it.

Every response carries `Content-Security-Policy` (`script-src 'self'`),
`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: strict-origin-when-cross-origin` and a
`Permissions-Policy`; HSTS is added only on https requests.
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/pytest tests/test_check_package.py tests/test_cli.py tests/test_templates.py -q && bash scripts/gate.sh --help 2>/dev/null || true`

Expected: PASS. `tests/test_templates.py` is the guard for any wrapper text
that quotes the help strings.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/cli.py src/center_kb/hub.py src/center_kb/cipublish.py scripts/gate.sh docs/deploy-remote-mcp.md tests/test_check_package.py
git commit -m "docs: correct --hub help, resolve_hub docstring and the deploy doc; echo not print (L19, L20, L24, M15)"
```

---

### Task 18: release 0.24.0

**Files:**
- Modify: `pyproject.toml` (version), `CHANGELOG.md`

**Interfaces:** none.

- [ ] **Step 1: Run the whole suite and the gate**

Run: `.venv/Scripts/pytest tests -q`

Expected: PASS, 0 failed. Then:

Run: `.venv/Scripts/ruff check src tests`

Expected: `All checks passed!`

- [ ] **Step 2: Verify against real data**

```bash
.venv/Scripts/kb doctor --kb-dir .kb
```

Expected: `kb doctor: OK`, exit 0. This is the spec's pre-merge gate for
the strict-models and new-doctor-check changes — a failure here is a real
finding in the repo's own KB and must be reported, not suppressed.

- [ ] **Step 3: Bump the version**

`pyproject.toml`: `version = "0.24.0"`.

- [ ] **Step 4: Write the CHANGELOG entry**

```markdown
## 0.24.0

### Breaking

- The `/ui` session cookie is now a signed, expiring value derived from the
  token (`center_kb_session`) instead of the token itself
  (`center_kb_token`). Every browser session needs one re-login. New:
  `POST /ui/logout`.
- `Manifest`, `SectionEntry`, `IndexEntry` and `KBIndex` reject unknown
  keys. A typo'd manifest key (`sumary:` for `summary:`) used to load and
  publish an empty L1 summary; it is now an error. The federation index
  stays permissive on purpose, so an older install can still read a newer
  hub.
- Eight commands that exited 2 on a misconfiguration now exit 1. Exit 2
  means citation stale only (`kb resolve`, `kb doctor --context`,
  `kb ba lint --fail-on-stale`). Click still emits its own 2 for a bad flag.
- `kb doctor` now fails trees it previously called OK: duplicate section
  ids, `## ` headings absent from the manifest, stale `tokens:` counts, and
  published content modified in place on the hub. A KB that was green can
  go red on upgrade with nothing having changed on disk — run `kb build`
  and `kb reindex` as the messages say.

### Added

- Security headers on every response: CSP (`script-src 'self'`),
  `X-Frame-Options: DENY`, nosniff, `Referrer-Policy`,
  `Permissions-Policy`; HSTS on https only.
- `federation/index.yaml` records `content_sha256` per snapshot, written by
  `kb reindex`, so `kb doctor` at the hub detects tampering. Snapshots
  published before 0.24 report "not verified" rather than failing.
- `kb diff` reports section title changes and manifest reorders.

### Fixed

- `kb doctor` no longer dies with a traceback on an invalid
  `.kb/config.yaml` — the guard lives in the shared hub funnel, so the
  other 10 hub commands are covered too, and doctor's own
  "config.yaml is invalid" check finally runs.
- Failed authentication over `Authorization` now shares the login form's
  rate-limit bucket; the lockout can no longer be side-stepped by using the
  header.
- A corrupt published snapshot renders an error page (503) instead of a
  bare 500 on `/api/docs/<doc>` and `/ui/docs/<doc>`.
- `/api/health` returns liveness only to unauthenticated callers.
- The login form caps its request body and its pages are `no-store`.
- REST and Web UI `tokens` count only the text the response carries;
  `kb query`, `kb get` and `/api/search` now surface the stale-hub-cache
  note MCP already had.
- Three doctor code paths that failed open on an unreadable config now fail
  closed, matching `kb publish`.
- `ruff` runs `BLE`, `RUF100` and `S` in addition to the defaults, so the
  `# noqa: BLE001` markers in `src/` are live and dead ones are flagged.
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore(release): 0.24.0 — reviewer H batch"
```

---

## Self-Review Notes

Checked against the spec, 2026-09-17:

- **Spec coverage.** § 1 → Tasks 1-2. § 2 → Task 3. § 3 → Tasks 4-6. § 4 →
  Task 7. § 5 → Tasks 9-13. § 6 → Tasks 8, 14-17. § 7 → tests inside each
  task. § 8 → Task 18. Optional H3(c) → Task 6 Step 7. L26 is a documented
  non-action per spec decision 14 and has no task, by design.
- **Task/group mapping.** The spec's six groups became 18 tasks: each web
  concern is separately reviewable (session, headers, limiter, error
  handler, the small-items batch), and the doctor checks split by what they
  read (manifest ids, token counts, hub digests).
- **Sequencing.** Tasks 1, 2, 5, 6, 7, 8, 14, 17 touch `cli.py`; Tasks
  9-13 touch `web/`. Run 9-13 as one sequence and the `cli.py` tasks as
  another; do not run two `cli.py` tasks concurrently in the same checkout.
- **Type consistency.** `_CONFIG_READ_ERRORS` (Task 1) is used by name in
  Tasks 2, 12. `make_session`/`verify_session`/`SESSION_MAX_AGE`/
  `cookie_is_secure` (Task 9) are used in Tasks 11, 13.
  `is_authorized_request` (Task 13) uses `verify_session` from Task 9.
  `content_tokens` (Task 14) is added in `query.py` and read in both web
  surfaces. `entry_content_digest` (Task 6) wraps `_fed_tree_digest` so
  `federation.py` never imports a private name from `doctor.py`.
- **Known unknowns flagged inside tasks rather than guessed:** the exact
  fixture names in the existing web tests (Tasks 9-13 say "reuse the
  existing client fixture"), whether `tests/test_diff.py` has a shared
  worktree fixture (Task 7 Step 1), `installed_version`'s exact return
  shape (Task 17 Step 1), and whether `_hub_or_exit`'s existing stale
  warning already covers `kb query`/`kb get` (Task 14 Step 5). Each says
  "read it first" rather than inventing a name.
