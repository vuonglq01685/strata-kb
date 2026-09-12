# Federation / publish / intake / CI Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all 19 findings of reviewer D — make the hub's review gate structural instead of conventional, stop the hub from holding credentials, and make the local release gate match CI.

**Architecture:** One new pure module, `src/center_kb/pubgate.py`, owns every rule that decides whether and how a publish may write to a hub (registry identity, mode selection, repo-id normalisation, the publish allowlist); `publish.publish()`, `publish.publish_federation()` and `intake.authorize()` all call it. New git primitives — a credential-free clone/push and `git worktree` handling — go into `gitio.py`. The intake writes each publish in its own temporary worktree so the serving clone never leaves the default branch.

**Tech Stack:** Python 3.11+, typer, pydantic v2, starlette, pytest (no mocking library — real filesystem, real git), ruff, hatch, uv.

**Spec:** `docs/superpowers/specs/2026-09-11-federation-publish-ci-review-fixes-design.md`

## Global Constraints

- **No new runtime dependency.** `uv.lock` must not need regenerating; the T2 gate runs `uv lock --check`.
- **Fail closed, no escape hatch.** Every gate violation is exit 1 with a message naming the way forward. Do not add `--allow-direct`, `--no-allowlist` or any equivalent flag.
- **Governance is opt-in per hub.** A hub with no `federation/registry.yaml`, or one whose `repos:` is empty, keeps today's behaviour.
- **Self-publish is exempt from governance entirely** — from the registry identity check and from the direct-push refusal. Keyed on `handle.root.resolve() == gitio.git_root(kb_abs).resolve()`, never on a flag.
- **No mocking library.** Tests run on a real filesystem and real git, using the existing `run_git`, `git_kb`, `hub_worktree` and `make_fed_entry` fixtures in `tests/conftest.py`.
- **Files stay focused.** `pubgate.py` holds no I/O — no filesystem, no subprocess, no network. Callers read and pass in.
- **Version:** this batch ships as `0.21.0`. `pyproject.toml` and the CHANGELOG are updated in the final task, not before.
- **Line endings:** every file written by the code uses `newline="\n"`, matching the existing `write_text(..., newline="\n")` convention.
- **Error messages are user-facing prose**, lower-case first word, naming the concrete fix — match the tone of the existing `PublishError` messages in `publish.py`.

---

### Task 1: `pubgate.normalize_repo_id` — repo-id rules

Closes F-D8's rule half. Pure; no callers change yet.

**Files:**
- Create: `src/center_kb/pubgate.py`
- Test: `tests/test_pubgate.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `pubgate.GateError`, `pubgate.REPO_ID_RE`, `pubgate.REPO_ID_MAX`, `pubgate.WIN32_DEVICES`, `pubgate.normalize_repo_id(rid: str, existing: Iterable[str] = ()) -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pubgate.py`:

```python
import pytest

from center_kb import pubgate


@pytest.mark.parametrize("rid", ["repo-alpha", "a", "a.b", "a_b", "A1", "kb-hub"])
def test_valid_repo_ids_pass_through(rid):
    assert pubgate.normalize_repo_id(rid) == rid


@pytest.mark.parametrize(
    "rid",
    ["", ".", "..", "../evil", "a/b", "a\\b", "C:evil", "évil", " victim", "victim "],
)
def test_invalid_shapes_are_refused(rid):
    with pytest.raises(pubgate.GateError):
        pubgate.normalize_repo_id(rid)


def test_over_long_repo_id_is_refused():
    with pytest.raises(pubgate.GateError, match="the limit is 64"):
        pubgate.normalize_repo_id("x" * 300)


@pytest.mark.parametrize("rid", ["victim.", "victim.."])
def test_trailing_dot_is_refused(rid):
    with pytest.raises(pubgate.GateError, match="ends with a dot"):
        pubgate.normalize_repo_id(rid)


@pytest.mark.parametrize("rid", ["CON", "con", "NUL", "COM1", "lpt9", "CON.md"])
def test_reserved_windows_device_names_are_refused(rid):
    with pytest.raises(pubgate.GateError, match="reserved Windows device name"):
        pubgate.normalize_repo_id(rid)


def test_case_insensitive_collision_with_a_sibling_is_refused():
    with pytest.raises(pubgate.GateError, match="collides with the existing entry 'victim'"):
        pubgate.normalize_repo_id("VICTIM", existing=["victim", "other"])


def test_republishing_the_same_entry_is_not_a_collision():
    assert pubgate.normalize_repo_id("victim", existing=["victim"]) == "victim"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_pubgate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.pubgate'`

- [ ] **Step 3: Write the implementation**

Create `src/center_kb/pubgate.py`:

```python
"""Every rule that decides whether and how a publish may write to a hub.

Pure by design: no filesystem, no subprocess, no network. Callers read the
registry, the remote URL and the existing entry names, then pass them in.
That keeps each of these -- they are the security rules -- a table test
rather than something only a real hub can exercise.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

REPO_ID_MAX = 64
REPO_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
WIN32_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


class GateError(RuntimeError):
    """A publish was refused. The message is user-facing; callers exit 1."""


def normalize_repo_id(rid: str, existing: Iterable[str] = ()) -> str:
    """The repo-id, or GateError naming why it cannot become a hub directory.

    `existing` is the entry directory names already under federation/ on the
    hub. The byte-wise regex alone is not enough: Path.resolve() normalises
    a trailing dot and a case difference textually, so the escape guard in
    publish._snapshot passes and Win32 then folds the new directory onto a
    sibling entry -- overwriting it, and pushing an aggregate index that
    disagrees with the committed tree.
    """
    if not REPO_ID_RE.fullmatch(rid) or rid in {".", ".."}:
        raise GateError(
            f"repo-id '{rid}' is invalid -- only letters/digits/._- allowed, "
            "no path separators"
        )
    if len(rid) > REPO_ID_MAX:
        raise GateError(
            f"repo-id '{rid[:24]}...' is {len(rid)} characters -- the limit is "
            f"{REPO_ID_MAX}"
        )
    if rid.endswith("."):
        raise GateError(
            f"repo-id '{rid}' ends with a dot -- Windows strips it silently, "
            "which would fold this entry onto a sibling"
        )
    stem = rid.split(".", 1)[0]
    if stem.upper() in WIN32_DEVICES:
        raise GateError(
            f"repo-id '{rid}' uses the reserved Windows device name '{stem}' -- "
            "pick another id"
        )
    for name in existing:
        if name != rid and name.casefold() == rid.casefold():
            raise GateError(
                f"repo-id '{rid}' collides with the existing entry '{name}' on a "
                "case-insensitive filesystem -- publishing would overwrite it"
            )
    return rid
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_pubgate.py -q`
Expected: PASS (all parametrised cases)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/pubgate.py tests/test_pubgate.py
git commit -m "feat(pubgate): repo-id rules that survive case-folding and Win32 (F-D8)"
```

---

### Task 2: `pubgate.owner_repo_from_remote` and `resolve_identity`

Closes F-D1's rule half. Still pure; still no callers.

**Files:**
- Modify: `src/center_kb/pubgate.py`
- Test: `tests/test_pubgate.py`

**Interfaces:**
- Consumes: `pubgate.GateError` (Task 1).
- Produces: `pubgate.owner_repo_from_remote(url: str) -> str | None`, `pubgate.resolve_identity(registry_map: dict[str, str], remote_url: str, requested_rid: str | None, hub_label: str) -> str`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pubgate.py`:

```python
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/org/repo.git", "org/repo"),
        ("https://github.com/org/repo", "org/repo"),
        ("https://x-access-token:ghs_SECRET@github.com/org/repo.git", "org/repo"),
        ("git@github.com:org/repo.git", "org/repo"),
        ("ssh://git@github.com/org/repo.git", "org/repo"),
        ("https://gitlab.com/group/sub/repo.git", "group/sub/repo"),
        ("https://github.com/org/repo.git/", "org/repo"),
    ],
)
def test_owner_repo_parsed_from_remote(url, expected):
    assert pubgate.owner_repo_from_remote(url) == expected


@pytest.mark.parametrize("url", ["", "/srv/kb-hub", "C:\\hubs\\kb-hub", "https://github.com/org"])
def test_local_paths_and_incomplete_urls_have_no_owner_repo(url):
    assert pubgate.owner_repo_from_remote(url) is None


REG = {"org/victim": "victim", "Org/Attacker": "attacker"}


def test_registry_maps_the_publisher_to_its_own_repo_id():
    rid = pubgate.resolve_identity(REG, "git@github.com:org/victim.git", None, "hub")
    assert rid == "victim"


def test_registry_lookup_is_case_insensitive():
    rid = pubgate.resolve_identity(REG, "https://github.com/ORG/Attacker.git", None, "hub")
    assert rid == "attacker"


def test_requesting_another_repos_id_is_refused():
    with pytest.raises(pubgate.GateError, match="maps 'org/attacker' to repo-id 'attacker'"):
        pubgate.resolve_identity(
            REG, "https://github.com/org/attacker.git", "victim", "hub"
        )


def test_unregistered_publisher_is_refused_with_the_registry_hint():
    with pytest.raises(pubgate.GateError, match="is not registered on hub"):
        pubgate.resolve_identity(REG, "https://github.com/org/stranger.git", None, "hub")


def test_publisher_without_a_remote_is_pointed_at_ci_publish():
    with pytest.raises(pubgate.GateError, match="kb ci-publish"):
        pubgate.resolve_identity(REG, "", None, "hub")


def test_matching_requested_repo_id_is_accepted():
    rid = pubgate.resolve_identity(REG, "https://github.com/org/victim", "victim", "hub")
    assert rid == "victim"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_pubgate.py -q`
Expected: FAIL — `AttributeError: module 'center_kb.pubgate' has no attribute 'owner_repo_from_remote'`

- [ ] **Step 3: Write the implementation**

Append to `src/center_kb/pubgate.py`:

```python
# scp-style remote: [user@]host:path/to/repo.git
_SCP_RE = re.compile(r"^[^/@]+@(?P<host>[^:/]+):(?P<path>.+)$")


def owner_repo_from_remote(url: str) -> str | None:
    """'owner/repo' (or 'group/sub/repo') from a git remote URL.

    None for a local path, an empty remote, or a URL with no repo path --
    which is the caller's signal that this publisher cannot be identified.
    Embedded credentials are dropped: the URL shape the CI templates use is
    https://x-access-token:<token>@github.com/org/repo.git.
    """
    text = (url or "").strip()
    if not text:
        return None
    m = _SCP_RE.match(text)
    if m:
        path = m.group("path")
    elif "://" in text:
        rest = text.split("://", 1)[1]
        rest = rest.split("@", 1)[-1]  # drop user:token@
        if "/" not in rest:
            return None
        path = rest.split("/", 1)[1]  # drop host[:port]
    else:
        return None
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    return "/".join(parts)


def resolve_identity(
    registry_map: dict[str, str],
    remote_url: str,
    requested_rid: str | None,
    hub_label: str,
) -> str:
    """The repo-id a governed hub accepts from this publisher.

    `registry_map` is {owner/repo: repo_id}, flattened by the caller from
    federation/registry.yaml, and is never empty -- an ungoverned hub does
    not reach here.

    This is a MISTAKE guard, not an authentication boundary: the remote URL
    is self-asserted by the publisher. The boundary is the review route a
    governed hub forces (see decide_mode) plus branch protection on the hub.
    """
    owner_repo = owner_repo_from_remote(remote_url)
    if owner_repo is None:
        raise GateError(
            f"hub '{hub_label}' is governed by federation/registry.yaml but this "
            "repo has no git remote to identify it -- publish through "
            "`kb ci-publish`, or ask the hub owner to remove the registry"
        )
    lookup = {key.casefold(): (key, value) for key, value in registry_map.items()}
    hit = lookup.get(owner_repo.casefold())
    if hit is None:
        raise GateError(
            f"repo '{owner_repo}' is not registered on hub '{hub_label}' -- open a "
            f"PR on the hub adding `{owner_repo}: <repo-id>` under `repos:` in "
            "federation/registry.yaml"
        )
    registered_repo, mapped = hit
    if requested_rid and requested_rid != mapped:
        raise GateError(
            f"registry maps '{registered_repo.casefold()}' to repo-id '{mapped}', "
            f"not '{requested_rid}' -- drop --repo-id, or ask the hub owner to "
            "change the registry"
        )
    return mapped
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_pubgate.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/pubgate.py tests/test_pubgate.py
git commit -m "feat(pubgate): registry identity for the git publish path (F-D1)"
```

---

### Task 3: `pubgate.decide_mode` — no silent direct push

Closes F-D2's rule half.

**Files:**
- Modify: `src/center_kb/pubgate.py`
- Test: `tests/test_pubgate.py`

**Interfaces:**
- Consumes: `pubgate.GateError` (Task 1).
- Produces: `pubgate.decide_mode(explicit: str, has_remote: bool, can_pr: bool, governed: bool, hub_label: str) -> Literal["pr", "direct"]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pubgate.py`:

```python
@pytest.mark.parametrize(
    "explicit,has_remote,can_pr,governed,expected",
    [
        ("direct", False, False, False, "direct"),
        ("direct", True, True, False, "direct"),
        ("direct", False, False, True, "direct"),   # local-path governed hub
        ("pr", True, True, False, "pr"),
        ("auto", False, False, False, "direct"),    # README:479's stated behaviour
        ("auto", False, False, True, "direct"),
        ("auto", True, True, False, "pr"),
        ("auto", True, True, True, "pr"),
    ],
)
def test_mode_table_accepted_rows(explicit, has_remote, can_pr, governed, expected):
    assert (
        pubgate.decide_mode(explicit, has_remote, can_pr, governed, "hub") == expected
    )


def test_governed_remote_hub_refuses_direct():
    with pytest.raises(pubgate.GateError, match="takes contributions by PR"):
        pubgate.decide_mode("direct", True, True, True, "hub")


def test_pr_without_a_remote_is_refused():
    with pytest.raises(pubgate.GateError, match="has no git remote"):
        pubgate.decide_mode("pr", False, False, False, "hub")


@pytest.mark.parametrize("explicit", ["pr", "auto"])
def test_remote_hub_that_cannot_open_a_pr_is_refused_with_two_exits(explicit):
    with pytest.raises(pubgate.GateError) as exc:
        pubgate.decide_mode(explicit, True, False, False, "hub")
    assert "--pr" in str(exc.value)
    assert "--direct" in str(exc.value)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_pubgate.py -q`
Expected: FAIL — `AttributeError: module 'center_kb.pubgate' has no attribute 'decide_mode'`

- [ ] **Step 3: Write the implementation**

Append to `src/center_kb/pubgate.py`:

```python
Mode = Literal["pr", "direct"]

_NO_PR_MESSAGE = (
    "hub '{hub}' has a git remote but `gh` cannot open a pull request on it "
    "(is `gh` installed and authenticated for that host?) -- either fix that "
    "and re-run with --pr, or re-run with --direct if you accept publishing "
    "without review"
)


def decide_mode(
    explicit: str,
    has_remote: bool,
    can_pr: bool,
    governed: bool,
    hub_label: str,
) -> Mode:
    """"auto" | "pr" | "direct" -> the mode to run, or GateError.

    Replaces the `"github" in remote_url` substring test, which routed every
    GitLab/Gitea/Bitbucket/self-hosted hub -- and any GitHub hub on a machine
    without `gh` -- to a silent direct push onto the hub's default branch.
    `can_pr` is decided by asking `gh` (see ghio.can_open_pr), not by parsing
    the URL: a GitHub Enterprise hub reached through GH_HOST answers yes, and
    a hub at .../github-mirror-hub.git answers no.
    """
    if explicit == "direct":
        if governed and has_remote:
            raise GateError(
                f"hub '{hub_label}' is governed by federation/registry.yaml -- it "
                "takes contributions by PR (`kb publish --pr`) or through "
                "`kb ci-publish`, not by direct push"
            )
        return "direct"
    if explicit == "pr":
        if not has_remote:
            raise GateError(
                f"hub '{hub_label}' has no git remote -- there is nothing to open "
                "a PR against; publish without --pr to commit locally"
            )
        if not can_pr:
            raise GateError(_NO_PR_MESSAGE.format(hub=hub_label))
        return "pr"
    if not has_remote:
        return "direct"
    if can_pr:
        return "pr"
    raise GateError(_NO_PR_MESSAGE.format(hub=hub_label))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_pubgate.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/pubgate.py tests/test_pubgate.py
git commit -m "feat(pubgate): mode selection that never silently direct-pushes (F-D2)"
```

---

### Task 4: `pubgate.split_allowlist` — KB artefacts only

Closes F-D6's rule half.

**Files:**
- Modify: `src/center_kb/pubgate.py`
- Test: `tests/test_pubgate.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `pubgate.is_kb_artifact(relpath: str) -> bool`, `pubgate.split_allowlist(manifest: dict[str, str]) -> tuple[dict[str, str], list[str]]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pubgate.py`:

```python
@pytest.mark.parametrize(
    "rel",
    [
        "index.yaml",
        "demo-doc/_manifest.yaml",
        "demo-doc/ch1.md",
        "demo-doc/ch1.raw.md",
        "demo-doc/assets/" + "a" * 64 + ".png",
        # one and two levels deeper: a federation/ source, nested tiers included
        "child/index.yaml",
        "child/_meta.yaml",
        "mid/deep/demo-doc/ch1.md",
        "mid/deep/demo-doc/assets/" + "b" * 64 + ".webp",
    ],
)
def test_kb_artifacts_are_kept(rel):
    assert pubgate.is_kb_artifact(rel) is True


@pytest.mark.parametrize(
    "rel",
    [
        "config.yaml",
        ".env",
        ".gitkeep",
        "demo-doc/ch1.md.bak",
        "demo-doc/notes.txt",
        "demo-doc/.hidden/ch1.md",
        "_assets.yaml",
        "child/_assets.yaml",
        "demo-doc/assets/nested/x.png",
    ],
)
def test_everything_else_is_skipped(rel):
    assert pubgate.is_kb_artifact(rel) is False


def test_split_allowlist_reports_what_it_dropped():
    manifest = {
        "index.yaml": "a",
        "config.yaml": "b",
        ".env": "c",
        "demo-doc/ch1.md": "d",
    }
    kept, skipped = pubgate.split_allowlist(manifest)
    assert kept == {"index.yaml": "a", "demo-doc/ch1.md": "d"}
    assert skipped == [".env", "config.yaml"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_pubgate.py -q`
Expected: FAIL — `AttributeError: module 'center_kb.pubgate' has no attribute 'is_kb_artifact'`

- [ ] **Step 3: Write the implementation**

Append to `src/center_kb/pubgate.py` (add `from pathlib import PurePosixPath` to the imports at the top of the file):

```python
_KEEP_BASENAMES = frozenset({"index.yaml", "_meta.yaml", "_manifest.yaml"})


def is_kb_artifact(relpath: str) -> bool:
    """Is this posix relpath something a publish is allowed to mirror?

    The rule is depth-independent on purpose, so one definition serves the
    .kb/ source, the federation/ source of a hub-to-hub publish (nested
    tiers included) and the extracted tar of an intake upload.

    _assets.yaml is deliberately NOT an artefact: it is hub-owned
    bookkeeping written by assetstore.divert_and_record, never copied in
    from a source.
    """
    parts = PurePosixPath(relpath).parts
    if not parts or any(p.startswith(".") for p in parts):
        return False
    name = parts[-1]
    if name in _KEEP_BASENAMES or name.endswith(".md"):
        return True
    return len(parts) >= 2 and parts[-2] == "assets"


def split_allowlist(manifest: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """(kept, skipped) -- `skipped` is sorted, for the caller's [warn] line."""
    kept = {rel: sha for rel, sha in manifest.items() if is_kb_artifact(rel)}
    skipped = sorted(set(manifest) - set(kept))
    return kept, skipped
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_pubgate.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/pubgate.py tests/test_pubgate.py
git commit -m "feat(pubgate): a publish allowlist for KB artefacts (F-D6)"
```

---

### Task 5: `ghio.can_open_pr` + wire `decide_mode` into both publish paths

Closes F-D2 end to end, and the pre-push half of F-D9: PR mode probes `gh` **before** `gitio.push_branch` force-pushes, so a failing `gh pr create` can no longer leave content on the remote with no PR.

**Files:**
- Modify: `src/center_kb/ghio.py`
- Modify: `src/center_kb/publish.py:265-274` (in `publish`), `publish.py:356-371` (in `publish_federation`), `publish.py:438-449` (in `_publish_pr`)
- Test: `tests/test_ghio.py`, `tests/test_publish_mode.py` (new)

**Interfaces:**
- Consumes: `pubgate.decide_mode`, `pubgate.GateError` (Task 3).
- Produces: `ghio.can_open_pr(root: Path) -> bool`; `publish.publish(...)` and `publish.publish_federation(...)` raise `pubgate.GateError` instead of silently choosing `direct`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_publish_mode.py`:

```python
import pytest

from center_kb import pubgate
from center_kb.publish import publish


@pytest.fixture
def hub_with_bare_remote(hub_worktree, run_git, tmp_path):
    """A hub whose origin is a bare repo -- i.e. a remote that is not GitHub."""
    origin = tmp_path / "hub-remote.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(hub_worktree, "remote", "add", "origin", str(origin))
    run_git(hub_worktree, "push", "-u", "origin", "HEAD")
    return hub_worktree, origin


def test_auto_refuses_instead_of_pushing_to_a_non_github_remote(
    git_kb, hub_with_bare_remote, monkeypatch, run_git
):
    hub, origin = hub_with_bare_remote
    monkeypatch.setattr("center_kb.ghio.can_open_pr", lambda root: False)
    before = run_git(origin, "rev-parse", "HEAD")
    with pytest.raises(pubgate.GateError) as exc:
        publish(git_kb["kb"], str(hub), repo_id="demo-kb")
    assert "--pr" in str(exc.value) and "--direct" in str(exc.value)
    assert run_git(origin, "rev-parse", "HEAD") == before


def test_explicit_direct_still_publishes_to_a_remote_hub(
    git_kb, hub_with_bare_remote, run_git
):
    hub, origin = hub_with_bare_remote
    report = publish(git_kb["kb"], str(hub), repo_id="demo-kb", mode="direct")
    assert report.mode == "direct"
    assert (hub / "federation" / "demo-kb" / "index.yaml").exists()


def test_auto_still_picks_direct_for_a_local_path_hub(git_kb, hub_worktree):
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    assert report.mode == "direct"


def test_pr_mode_refuses_before_pushing_when_gh_cannot_see_the_hub(
    git_kb, hub_with_bare_remote, monkeypatch, run_git
):
    hub, origin = hub_with_bare_remote
    monkeypatch.setattr("center_kb.ghio.gh_available", lambda: True)
    monkeypatch.setattr("center_kb.ghio.can_open_pr", lambda root: False)
    with pytest.raises(pubgate.GateError):
        publish(git_kb["kb"], str(hub), repo_id="demo-kb", mode="pr")
    branches = run_git(origin, "branch", "--list", "publish/demo-kb")
    assert branches.strip() == ""
```

Append to `tests/test_ghio.py`:

```python
def test_can_open_pr_is_false_without_gh(tmp_path, monkeypatch):
    from center_kb import ghio

    monkeypatch.setattr(ghio, "gh_available", lambda: False)
    assert ghio.can_open_pr(tmp_path) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_publish_mode.py tests/test_ghio.py -q`
Expected: FAIL — `AttributeError: module 'center_kb.ghio' has no attribute 'can_open_pr'`, and `test_auto_refuses_...` fails because `publish` currently pushes.

- [ ] **Step 3: Write the implementation**

Append to `src/center_kb/ghio.py`:

```python
def can_open_pr(root: Path) -> bool:
    """Can `gh` actually open a pull request on this repo's origin?

    Asked once, before anything is pushed. Replaces the old
    `"github" in remote_url` substring test in publish.py, which was wrong
    in both directions: it routed .../github-mirror-hub.git to PR mode (and
    crashed after force-pushing) and every GitLab/Gitea/self-hosted hub to a
    silent direct push. `gh repo view` respects GH_HOST, so a GitHub
    Enterprise hub answers correctly too.
    """
    if not gh_available():
        return False
    proc = _run_gh(root, "repo", "view", "--json", "name")
    return proc.returncode == 0
```

In `src/center_kb/publish.py`, add `from center_kb import pubgate` to the imports, then replace the auto-mode block in `publish()` (currently `publish.py:265-274`):

```python
    mode = pubgate.decide_mode(
        mode,
        has_remote=gitio.has_remote(handle.root),
        can_pr=ghio.can_open_pr(handle.root),
        governed=False,  # Task 6 replaces this with the real registry check
        hub_label=gitio.redact_url(hub_ref),
    )
    if mode == "pr":
        return _publish_pr(kb_abs, handle, rid, source_commit)
    return _publish_direct(kb_abs, handle, rid, source_commit, max_retries)
```

Replace the identical block in `publish_federation()` (currently `publish.py:357-371`):

```python
    mode = pubgate.decide_mode(
        mode,
        has_remote=gitio.has_remote(handle.root),
        can_pr=ghio.can_open_pr(handle.root),
        governed=False,  # Task 6 replaces this with the real registry check
        hub_label=gitio.redact_url(hub_ref),
    )
    if mode == "pr":
        return _publish_pr(
            fed_src, handle, rid, source_commit, snapshot_fn=_snapshot_federation
        )
    return _publish_direct(
        fed_src, handle, rid, source_commit, max_retries,
        snapshot_fn=_snapshot_federation,
    )
```

In `_publish_pr`, replace the `gh_available()` precondition (currently `publish.py:445-449`) with the stronger probe:

```python
    if not ghio.can_open_pr(handle.root):
        raise PublishError(
            "PR mode needs the GitHub CLI able to see the hub repo -- install "
            "`gh` (https://cli.github.com), authenticate it for the hub's host, "
            "or run `kb publish --direct` if direct pushes are allowed"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_publish_mode.py tests/test_ghio.py tests/test_publish.py -q`
Expected: PASS. If a pre-existing test in `tests/test_publish.py` asserted the old auto-mode behaviour for a remote hub, update it to pass `mode="direct"` explicitly — that is the behaviour change this task ships.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/ghio.py src/center_kb/publish.py tests/test_publish_mode.py tests/test_ghio.py tests/test_publish.py
git commit -m "fix(publish): ask gh whether a PR is possible, never silently direct-push (F-D2, F-D9)"
```

---

### Task 6: the registry gate in `publish()` and `publish_federation()`

Closes F-D1 and F-D8 end to end. This is the CRITICAL finding.

**Files:**
- Modify: `src/center_kb/federation.py` (add `registry_map`)
- Modify: `src/center_kb/publish.py` — `publish()` and `publish_federation()`
- Test: `tests/test_publish_registry.py` (new)

**Interfaces:**
- Consumes: `pubgate.resolve_identity`, `pubgate.normalize_repo_id`, `pubgate.decide_mode` (Tasks 1–3).
- Produces: `federation.registry_map(registry: models.Registry) -> dict[str, str]`; `publish._governed_registry(handle) -> dict[str, str] | None`; `publish._existing_entry_names(handle) -> list[str]`. `publish.publish` and `publish.publish_federation` gain the keyword argument `self_publish: bool = False`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_publish_registry.py`:

```python
"""Reviewer D's F-D1 repro: a hub with a registry must not accept a snapshot
published under someone else's repo-id."""
import pytest
import yaml

from center_kb import models, pubgate
from center_kb.publish import publish


@pytest.fixture
def governed_hub(hub_worktree, run_git):
    fed = hub_worktree / "federation"
    fed.mkdir(exist_ok=True)
    (fed / "registry.yaml").write_text(
        yaml.safe_dump({"repos": {"org/victim": "victim"}}),
        encoding="utf-8",
        newline="\n",
    )
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "hub: register org/victim")
    return hub_worktree


def _set_remote(run_git, root, url):
    run_git(root, "remote", "add", "origin", url)


def test_registered_publisher_may_publish_its_own_id(governed_hub, git_kb, run_git):
    _set_remote(run_git, git_kb["root"], "https://github.com/org/victim.git")
    report = publish(git_kb["kb"], str(governed_hub), repo_id=None, mode="direct")
    assert report.repo_id == "victim"
    assert (governed_hub / "federation" / "victim" / "index.yaml").exists()


def test_unregistered_publisher_cannot_publish_as_another_repo(
    governed_hub, git_kb, run_git
):
    _set_remote(run_git, git_kb["root"], "https://github.com/org/attacker.git")
    with pytest.raises(pubgate.GateError, match="is not registered on hub"):
        publish(git_kb["kb"], str(governed_hub), repo_id="victim", mode="direct")
    assert not (governed_hub / "federation" / "victim").exists()


def test_registered_publisher_cannot_claim_a_different_repo_id(
    governed_hub, git_kb, run_git
):
    _set_remote(run_git, git_kb["root"], "https://github.com/org/victim.git")
    with pytest.raises(pubgate.GateError, match="not 'somebody-else'"):
        publish(git_kb["kb"], str(governed_hub), repo_id="somebody-else", mode="direct")


def test_ungoverned_hub_is_unaffected(hub_worktree, git_kb):
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="anything", mode="direct")
    assert report.repo_id == "anything"


def test_empty_registry_counts_as_ungoverned(hub_worktree, git_kb, run_git):
    fed = hub_worktree / "federation"
    fed.mkdir(exist_ok=True)
    (fed / "registry.yaml").write_text("repos: {}\n", encoding="utf-8", newline="\n")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "hub: empty registry")
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="anything", mode="direct")
    assert report.repo_id == "anything"


def test_unreadable_registry_fails_closed(hub_worktree, git_kb, run_git):
    fed = hub_worktree / "federation"
    fed.mkdir(exist_ok=True)
    (fed / "registry.yaml").write_text("repos: [not, a, mapping\n", encoding="utf-8")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "hub: broken registry")
    from center_kb.publish import PublishError

    with pytest.raises(PublishError, match="registry.yaml is invalid"):
        publish(git_kb["kb"], str(hub_worktree), repo_id="anything", mode="direct")


def test_case_folded_repo_id_cannot_clobber_a_sibling(hub_worktree, git_kb):
    publish(git_kb["kb"], str(hub_worktree), repo_id="victim", mode="direct")
    with pytest.raises(pubgate.GateError, match="collides with the existing entry"):
        publish(git_kb["kb"], str(hub_worktree), repo_id="VICTIM", mode="direct")
    assert (hub_worktree / "federation" / "victim" / "index.yaml").exists()


def test_reserved_device_name_is_refused_before_anything_is_written(
    hub_worktree, git_kb
):
    with pytest.raises(pubgate.GateError, match="reserved Windows device name"):
        publish(git_kb["kb"], str(hub_worktree), repo_id="CON", mode="direct")
    assert not (hub_worktree / "federation" / "CON").exists()


def test_registry_map_flattens_the_model():
    from center_kb import federation

    reg = models.Registry(repos={"org/repo": "rid"})
    assert federation.registry_map(reg) == {"org/repo": "rid"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_publish_registry.py -q`
Expected: FAIL — `test_unregistered_publisher_cannot_publish_as_another_repo` succeeds in publishing (this is F-D1), and `federation.registry_map` does not exist.

- [ ] **Step 3: Write the implementation**

Add to `src/center_kb/federation.py`, right after `load_registry`:

```python
def registry_map(registry: models.Registry) -> dict[str, str]:
    """{owner/repo: repo_id} -- the one accessor both write paths read through.

    Task 17 gives Registry an optional mapping form for pinning a workflow;
    this stays the shape callers see either way.
    """
    return dict(registry.repos)
```

In `src/center_kb/publish.py`, add these helpers above `publish()`:

```python
def _governed_registry(handle: hub_mod.HubHandle) -> dict[str, str] | None:
    """{owner/repo: repo_id} when the hub carries a non-empty registry, else None.

    An unreadable registry is fatal here exactly as it is in intake.authorize:
    a hub whose registry cannot be parsed must never be treated as ungoverned.
    """
    try:
        registry = federation.load_registry(handle.federation_dir)
    except federation.RegistryError as exc:
        raise PublishError(str(exc)) from exc
    return federation.registry_map(registry) or None


def _existing_entry_names(handle: hub_mod.HubHandle) -> list[str]:
    """Entry directory names directly under federation/ on the hub."""
    fed = handle.federation_dir
    if not fed.is_dir():
        return []
    return sorted(
        p.name
        for p in fed.iterdir()
        if p.is_dir() and p.name not in _FED_TOP_EXCLUDE
    )
```

`_FED_TOP_EXCLUDE` is defined at `publish.py:139`, below `_snapshot` — move that constant above `_snapshot` so both helpers can use it.

Replace the head of `publish()` (currently `publish.py:251-274`) with:

```python
    kb_abs = kb_dir.resolve()
    warn_legacy_ids(kb_abs)
    source_root = gitio.git_root(kb_abs)
    source_commit = gitio.head_commit(source_root)
    handle = hub_mod.resolve_hub(hub_ref)
    if handle is None:
        raise PublishError(f"could not reach hub '{gitio.redact_url(hub_ref)}'")
    hub_label = gitio.redact_url(hub_ref)
    # Self-publish -- a hub mirroring its own .kb/ into its own federation/ --
    # is exempt from governance: requiring the hub owner to register
    # themselves and open a PR against themselves would only break it.
    is_self = self_publish or handle.root.resolve() == source_root.resolve()
    registry_map = None if is_self else _governed_registry(handle)
    rid = repo_id or source_root.name
    if registry_map is not None:
        rid = pubgate.resolve_identity(
            registry_map, gitio.remote_url(source_root), repo_id, hub_label
        )
    rid = pubgate.normalize_repo_id(rid, _existing_entry_names(handle))
    _neutralize_excludes(handle.root)

    mode = pubgate.decide_mode(
        mode,
        has_remote=gitio.has_remote(handle.root),
        can_pr=ghio.can_open_pr(handle.root),
        governed=registry_map is not None,
        hub_label=hub_label,
    )
```

Change the signature to `def publish(kb_dir, hub_ref, repo_id=None, max_retries=3, mode="auto", self_publish=False) -> PublishReport:`.

In `publish_federation()`, apply the same treatment: after `handle` is resolved and the cycle guards have run, replace the `_REPO_ID_RE` check (currently `publish.py:308-311`) and the auto-mode block with:

```python
    hub_label = gitio.redact_url(hub_ref)
    registry_map = _governed_registry(handle)
    rid = repo_id or source_root.name
    if registry_map is not None:
        rid = pubgate.resolve_identity(
            registry_map, gitio.remote_url(source_root), repo_id, hub_label
        )
    rid = pubgate.normalize_repo_id(rid, _existing_entry_names(handle))
```

Note the ordering: `rid` is needed by the cycle guard's `forbidden` set, so this block must sit **after** `handle` is resolved and **before** `forbidden = {rid}`. Move the `handle`/`resolve_hub` block up accordingly, leaving the `fed_src` existence check first.

Then change the mode block to pass `governed=registry_map is not None` instead of the `governed=False` placeholder from Task 5.

Finally, delete `_REPO_ID_RE` from `publish.py` and update its two importers, `intake.py:67` and `intake.py:217`, to `from center_kb.pubgate import REPO_ID_RE` (keeping their existing `fullmatch` calls).

In `src/center_kb/cli.py`, the self-publish fall-through at `cli.py:1575-1578` passes `is_self` already — add it to the call:

```python
        report = publish_mod.publish(
            kb_dir, hub_ref,
            repo_id=effective_repo_id(repo_id, kb_dir), mode=mode,
            self_publish=is_self,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_publish_registry.py tests/test_publish.py tests/test_federation_registry.py tests/test_intake_core.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/federation.py src/center_kb/publish.py src/center_kb/intake.py src/center_kb/cli.py tests/test_publish_registry.py
git commit -m "fix(publish): enforce federation/registry.yaml on the git write path (F-D1, F-D8)"
```

---

### Task 7: the allowlist in every write path + the doctor warning

Closes F-D6 end to end.

**Files:**
- Modify: `src/center_kb/publish.py` — `_snapshot`, `_snapshot_federation`
- Modify: `src/center_kb/intake.py` — `intake_publish`
- Modify: `src/center_kb/doctor.py` — `check_hub`
- Modify: `src/center_kb/cli.py` — `_echo_publish_report` prints the skip warning
- Test: `tests/test_publish_allowlist.py` (new), `tests/test_doctor_hub.py`

**Interfaces:**
- Consumes: `pubgate.split_allowlist` (Task 4).
- Produces: `PublishReport.skipped: list[str]` (default `field(default_factory=list)`); `_snapshot`/`_snapshot_federation` return `tuple[int, bool, list[str]]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_publish_allowlist.py`:

```python
from center_kb.publish import publish


def test_config_yaml_and_dotfiles_never_reach_the_hub(git_kb, hub_worktree, run_git):
    kb = git_kb["kb"]
    (kb / "config.yaml").write_text(
        'hub: "https://x-access-token:ghs_SECRET@github.com/org/kb-hub.git"\n',
        encoding="utf-8",
        newline="\n",
    )
    (kb / ".env").write_text("AWS_SECRET_ACCESS_KEY=AKIAEXAMPLE\n", encoding="utf-8")
    (kb / "demo-doc" / "ch1-records.md.bak").write_text("stray\n", encoding="utf-8")
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "child: config + stray files")

    report = publish(kb, str(hub_worktree), repo_id="child", mode="direct")

    entry = hub_worktree / "federation" / "child"
    assert not (entry / "config.yaml").exists()
    assert not (entry / ".env").exists()
    assert not (entry / "demo-doc" / "ch1-records.md.bak").exists()
    assert (entry / "index.yaml").exists()
    assert (entry / "demo-doc" / "ch1-records.md").exists()
    assert report.skipped == [".env", "config.yaml", "demo-doc/ch1-records.md.bak"]


def test_an_already_mirrored_config_is_removed_on_the_next_publish(
    git_kb, hub_worktree, run_git
):
    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    leaked = hub_worktree / "federation" / "child" / "config.yaml"
    leaked.write_text("hub: secret\n", encoding="utf-8", newline="\n")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "hub: an old version mirrored config.yaml")

    (git_kb["kb"] / "demo-doc" / "ch1-records.md").write_text(
        "## 1.1 Records\n\nEdited.\n", encoding="utf-8", newline="\n"
    )
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "child: edit")
    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")

    assert not leaked.exists()
```

Append to `tests/test_doctor_hub.py`:

```python
def test_doctor_warns_about_a_non_allowlisted_file_in_an_entry(
    hub_worktree, git_kb, run_git
):
    from center_kb.doctor import check_hub
    from center_kb.hub import HubHandle
    from center_kb.publish import publish

    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    (hub_worktree / "federation" / "child" / "config.yaml").write_text(
        "hub: leftover\n", encoding="utf-8", newline="\n"
    )
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    assert any("config.yaml" in i.message and i.level == "warning" for i in issues)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_publish_allowlist.py tests/test_doctor_hub.py -q`
Expected: FAIL — `config.yaml` and `.env` are mirrored today (F-D6), and `PublishReport` has no `skipped`.

- [ ] **Step 3: Write the implementation**

In `src/center_kb/publish.py`, add `skipped: list[str] = field(default_factory=list)` to `PublishReport` (import `field` from `dataclasses`).

In `_snapshot`, after `local_man = hashsync.build_manifest(kb_abs)`:

```python
    local_man, skipped = pubgate.split_allowlist(local_man)
```

and change the two `return` statements to `return len(local_index.docs), False, skipped` and `return len(local_index.docs), True, skipped`.

In `_snapshot_federation`, after `src_man = hashsync.build_manifest(fed_src, exclude=_FED_TOP_EXCLUDE)`:

```python
    src_man, skipped = pubgate.split_allowlist(src_man)
```

and return `n_docs, False, skipped` / `n_docs, True, skipped`.

Update both call sites — `_publish_direct` and `_publish_pr` — to unpack three values and pass `skipped` into the `PublishReport` they build:

```python
    n_docs, changed, skipped = snapshot_fn(kb_abs, handle, rid, source_commit)
```

```python
    return PublishReport(rid, source_commit, n_docs, pushed, mode="direct", skipped=skipped)
```

In `src/center_kb/intake.py`'s `intake_publish`, after `local_man = hashsync.build_manifest(tmp_kb)` and the existing `local_man.pop(assetstore.RECORD_NAME, None)`:

```python
                from center_kb import pubgate

                local_man, skipped = pubgate.split_allowlist(local_man)
                for rel in skipped:
                    stray = tmp_kb / rel
                    if stray.is_file():
                        stray.unlink()
                if skipped:
                    logger.warning(
                        "intake: %d uploaded file(s) are not KB artefacts and were "
                        "not published: %s", len(skipped), ", ".join(skipped)
                    )
```

In `src/center_kb/doctor.py`'s `check_hub`, add a new loop directly after the existing slim-layout loop (the `for child in sorted(p for p in fed.iterdir() ...)` block, which walks only the top level and must stay as it is). Note `Issue.level` is `Literal["error", "warning"]` -- the value is `"warning"`, not `"warn"`:

```python
    if fed.is_dir():
        from center_kb import assetstore, pubgate
        from center_kb.federation import iter_entry_dirs

        for entry_rel, entry_dir in iter_entry_dirs(fed):
            strays = sorted(
                p.relative_to(entry_dir).as_posix()
                for p in entry_dir.rglob("*")
                if p.is_file()
                and p.name != assetstore.RECORD_NAME
                and not pubgate.is_kb_artifact(p.relative_to(entry_dir).as_posix())
            )
            if strays:
                issues.append(
                    Issue(
                        "warning",
                        f"federation/{entry_rel} holds file(s) a publish would "
                        f"never write: {', '.join(strays)} -- an older version "
                        "mirrored them; delete them on the hub, and rotate any "
                        "credential they contain",
                    )
                )
```

In `src/center_kb/cli.py`'s `_echo_publish_report`, print the warning before the existing lines:

```python
def _echo_publish_report(report) -> None:
    if getattr(report, "skipped", None):
        typer.secho(
            f"[warn] {len(report.skipped)} file(s) under .kb/ were not published "
            f"(allowlist): {', '.join(report.skipped)}",
            fg=typer.colors.YELLOW,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_publish_allowlist.py tests/test_doctor_hub.py tests/test_publish.py tests/test_intake_publish.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/publish.py src/center_kb/intake.py src/center_kb/doctor.py src/center_kb/cli.py tests/test_publish_allowlist.py tests/test_doctor_hub.py
git commit -m "fix(publish): mirror KB artefacts only, never config.yaml or dotfiles (F-D6)"
```

---

### Task 8: `kb reindex` commits only the index

Closes F-D5.

**Files:**
- Modify: `src/center_kb/cli.py:1640-1642` (the `reindex` command)
- Test: `tests/test_reindex_scope.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing new — a behaviour change in `kb reindex`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_reindex_scope.py`:

```python
from typer.testing import CliRunner

from center_kb.cli import app
from center_kb.publish import publish

runner = CliRunner()


def test_reindex_does_not_commit_hand_edited_or_untracked_content(
    git_kb, hub_worktree, run_git
):
    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    tampered = hub_worktree / "federation" / "child" / "demo-doc" / "ch1-records.md"
    tampered.write_text("TAMPERED unreviewed content\n", encoding="utf-8", newline="\n")
    rogue = hub_worktree / "federation" / "rogue"
    rogue.mkdir()
    (rogue / "index.yaml").write_text("docs: []\n", encoding="utf-8", newline="\n")

    result = runner.invoke(
        app, ["reindex", "--hub", str(hub_worktree), "--kb-dir", str(hub_worktree / ".kb")]
    )
    assert result.exit_code == 0, result.output

    committed = run_git(hub_worktree, "show", "--name-only", "--format=", "HEAD")
    assert "federation/child/demo-doc/ch1-records.md" not in committed
    assert "federation/rogue" not in committed
    head_content = run_git(
        hub_worktree, "show", "HEAD:federation/child/demo-doc/ch1-records.md"
    )
    assert "TAMPERED" not in head_content
    assert "federation/child/demo-doc/ch1-records.md" in result.output
    assert "federation/rogue" in result.output
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_reindex_scope.py -q`
Expected: FAIL — the tampered file and `federation/rogue/` are both in the reindex commit (F-D5).

- [ ] **Step 3: Write the implementation**

In `src/center_kb/cli.py`'s `reindex`, replace the commit call:

```python
    # Scope the commit the way _publish_direct already does. Committing all of
    # federation/ under a message that says "rebuild index" swept in hand-edited
    # content and untracked directories -- and publish's own error paths leave
    # exactly that behind.
    dirty_before = gitio._run(
        handle.root, "status", "--porcelain", "--", "federation"
    ).stdout.splitlines()
    committed = gitio.commit_paths(
        handle.root, "reindex: rebuild federation/index.yaml", ["federation/index.yaml"]
    )
    strays = sorted(
        line[3:].strip()
        for line in dirty_before
        if line[3:].strip() not in ("federation/index.yaml",)
    )
    if strays:
        typer.secho(
            "[warn] uncommitted content under federation/ was NOT committed by "
            f"reindex: {', '.join(strays)}",
            fg=typer.colors.YELLOW,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_reindex_scope.py tests/test_cli_hub.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/cli.py tests/test_reindex_scope.py
git commit -m "fix(reindex): commit federation/index.yaml only, warn about the rest (F-D5)"
```

---

### Task 9: honest publish output

Closes F-D17.

**Files:**
- Modify: `src/center_kb/publish.py` — `PublishReport`, `_publish_direct`
- Modify: `src/center_kb/cli.py:1455` — `_echo_publish_report`
- Test: `tests/test_publish.py`

**Interfaces:**
- Consumes: `PublishReport.skipped` (Task 7).
- Produces: `PublishReport.remote: bool = False`; `publish._reported_commit(handle, rid, source_commit, changed) -> str`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_publish.py`:

```python
def test_report_distinguishes_no_remote_from_nothing_to_push(
    git_kb, hub_with_origin, hub_worktree
):
    first = publish(git_kb["kb"], str(hub_with_origin), repo_id="demo-kb", mode="direct")
    assert first.remote is True and first.pushed is True

    second = publish(git_kb["kb"], str(hub_with_origin), repo_id="demo-kb", mode="direct")
    assert second.remote is True and second.pushed is False


def test_report_marks_a_hub_without_a_remote(git_kb, hub_worktree):
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb", mode="direct")
    assert report.remote is False


def test_a_no_change_publish_reports_the_commit_actually_snapshotted(
    git_kb, hub_worktree, run_git
):
    """_snapshot leaves _meta.yaml alone when nothing changed, so on a second
    publish after an unrelated commit the CLI was printing the source repo's
    new HEAD next to a hub entry that still records the old one."""
    from center_kb import gitio

    first = publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb", mode="direct")
    (git_kb["root"] / "README.md").write_text("unrelated
", encoding="utf-8", newline="
")
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "child: unrelated change outside .kb/")
    second = publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb", mode="direct")

    assert second.source_commit == first.source_commit
    assert second.source_commit != gitio.head_commit(git_kb["root"])


def test_cli_does_not_claim_a_hub_has_no_remote_when_it_does(
    git_kb, hub_with_origin
):
    from typer.testing import CliRunner

    from center_kb.cli import app

    runner = CliRunner()
    runner.invoke(
        app,
        ["publish", "--hub", str(hub_with_origin), "--repo-id", "demo-kb",
         "--kb-dir", str(git_kb["kb"]), "--direct"],
    )
    result = runner.invoke(
        app,
        ["publish", "--hub", str(hub_with_origin), "--repo-id", "demo-kb",
         "--kb-dir", str(git_kb["kb"]), "--direct"],
    )
    assert "hub has no remote" not in result.output
    assert "nothing to push" in result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_publish.py -q -k "remote or nothing_to_push"`
Expected: FAIL — `PublishReport` has no `remote`, and the CLI prints "commit only (hub has no remote)" for a hub that does have one.

- [ ] **Step 3: Write the implementation**

In `src/center_kb/publish.py`, add `remote: bool = False` to `PublishReport`, add the helper:

```python
def _reported_commit(
    handle: hub_mod.HubHandle, rid: str, source_commit: str, changed: bool
) -> str:
    """The commit the hub entry actually records.

    _snapshot deliberately leaves _meta.yaml alone when nothing changed, so
    reporting the source repo's current HEAD claims the hub holds a snapshot
    of a commit it has never seen. Most visible on a self-publish, where the
    previous publish's own commit moved HEAD.
    """
    if changed:
        return source_commit
    meta_path = handle.federation_dir / rid / "_meta.yaml"
    try:
        meta = models.load_yaml_model(meta_path, federation.FederationMeta)
    except (OSError, ValidationError, yaml.YAMLError):
        return source_commit
    return meta.source_commit or source_commit
```

`publish.py` imports neither today, so add `import yaml` and
`from pydantic import ValidationError` to its import block.

Then in `_publish_direct` build the report with both:

```python
    return PublishReport(
        rid,
        _reported_commit(handle, rid, source_commit, changed),
        n_docs, pushed, mode="direct",
        skipped=skipped, remote=gitio.has_remote(handle.root),
    )
```

Apply the same `_reported_commit(...)` call where `_publish_pr` builds its
`PublishReport`.

In `src/center_kb/cli.py`'s `_echo_publish_report`, replace the `action` line:

```python
    if report.pushed:
        action = "push"
    elif getattr(report, "remote", False):
        action = "commit only (nothing to push)"
    else:
        action = "commit only (hub has no remote)"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_publish.py tests/test_cli_hub.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/publish.py src/center_kb/cli.py tests/test_publish.py
git commit -m "fix(publish): stop reporting 'hub has no remote' for a hub that has one (F-D17)"
```

---

### Task 10: clean errors from every publish command

Closes the traceback half of F-D9.

**Files:**
- Modify: `src/center_kb/cli.py` — the `publish`, `ci-publish` and `reindex` handlers
- Test: `tests/test_cli_errors.py` (new)

**Interfaces:**
- Consumes: `pubgate.GateError` (Task 1), `ghio.GHError`.
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_errors.py`:

```python
from typer.testing import CliRunner

from center_kb.cli import app

runner = CliRunner()


def _invoke_publish(git_kb, hub, repo_id):
    return runner.invoke(
        app,
        ["publish", "--hub", str(hub), "--repo-id", repo_id,
         "--kb-dir", str(git_kb["kb"]), "--direct"],
    )


def test_over_long_repo_id_is_one_line_not_a_traceback(git_kb, hub_worktree):
    result = _invoke_publish(git_kb, hub_worktree, "x" * 300)
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "the limit is 64" in result.output


def test_reserved_device_name_is_one_line(git_kb, hub_worktree):
    result = _invoke_publish(git_kb, hub_worktree, "CON")
    assert result.exit_code == 1
    assert "Traceback" not in result.output


def test_a_failing_gh_pr_create_is_one_line(git_kb, hub_with_origin, monkeypatch):
    from center_kb import ghio

    monkeypatch.setattr(ghio, "can_open_pr", lambda root: True)
    monkeypatch.setattr(ghio, "pr_url_for_branch", lambda root, branch: "")

    def _boom(root, branch, title, body):
        raise ghio.GHError("gh pr create failed: HTTP 404")

    monkeypatch.setattr(ghio, "create_pr", _boom)
    result = runner.invoke(
        app,
        ["publish", "--hub", str(hub_with_origin), "--repo-id", "demo-kb",
         "--kb-dir", str(git_kb["kb"]), "--pr"],
    )
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "gh pr create failed" in result.output


def test_unreadable_registry_is_one_line(git_kb, hub_worktree, run_git):
    fed = hub_worktree / "federation"
    fed.mkdir(exist_ok=True)
    (fed / "registry.yaml").write_text("repos: [broken\n", encoding="utf-8")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "hub: broken registry")
    result = _invoke_publish(git_kb, hub_worktree, "demo-kb")
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "registry.yaml is invalid" in result.output
```

Note: `CliRunner` in this repo is invoked without `catch_exceptions=False`, so an
uncaught exception yields `exit_code == 1` with the traceback in
`result.output` — which is exactly what the `"Traceback" not in result.output`
assertion catches.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_cli_errors.py -q`
Expected: FAIL — `OSError`, `ghio.GHError` and `pubgate.GateError` are not in the handlers' `except` tuples, so each surfaces a traceback.

- [ ] **Step 3: Write the implementation**

In `src/center_kb/cli.py`, add `from center_kb import ghio, pubgate` to the local imports inside `publish()` and `ci_publish()`, and widen the three `except` tuples.

In `publish()`, both the hub-to-hub branch and the main branch:

```python
            except (
                publish_mod.PublishError, gitio.GitError, pubgate.GateError,
                ghio.GHError, OSError,
            ) as exc:
                typer.secho(str(exc), fg=typer.colors.RED)
                raise typer.Exit(1)
```

```python
    except (
        HubConfigError, publish_mod.PublishError, gitio.GitError,
        pubgate.GateError, ghio.GHError, OSError,
    ) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
```

In the intake branch of `publish()` and in `ci_publish()`, add `OSError` alongside the existing exceptions.

In `reindex()`, wrap the body's hub work:

```python
    try:
        handle = _hub_or_exit(hub, kb_dir)
        write_federation_index(handle.federation_dir)
    except (gitio.GitError, OSError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_cli_errors.py tests/test_cli_hub.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/cli.py tests/test_cli_errors.py
git commit -m "fix(cli): one clean line instead of a traceback from publish/reindex (F-D9)"
```

---

### Task 11: credential-free git — no token in `.git/config`, none on a command line

Closes F-D7.

**Files:**
- Modify: `src/center_kb/gitio.py`
- Modify: `src/center_kb/hub.py:66` (the cache key), `hub.py:32-34` (`_cache_base`), `hub.py:55-97` (`resolve_hub`)
- Modify: `src/center_kb/intake.py:389-396` (the token push)
- Modify: `src/center_kb/doctor.py` — `check_hub`
- Test: `tests/test_hub_credentials.py` (new), `tests/test_gitio.py`, `tests/test_doctor_hub.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `gitio.split_credentials(url: str) -> tuple[str, str | None]`, `gitio.credential_env(url: str, token: str | None) -> dict[str, str]`, `gitio.push_branch_with_token(root: Path, url: str, token: str, branch: str) -> None`. `gitio.clone(url, dest)` and `gitio.pull(root)` gain optional credential handling.

- [ ] **Step 1: Write the failing test**

Create `tests/test_hub_credentials.py`:

```python
import hashlib

import pytest

from center_kb import gitio, hub as hub_mod


CRED = "https://x-access-token:ghs_SECRETTOKEN@github.com/org/kb-hub.git"
STRIPPED = "https://github.com/org/kb-hub.git"


def test_split_credentials_separates_url_from_token():
    url, token = gitio.split_credentials(CRED)
    assert url == STRIPPED
    assert token == "ghs_SECRETTOKEN"


def test_split_credentials_leaves_a_plain_url_alone():
    assert gitio.split_credentials(STRIPPED) == (STRIPPED, None)


def test_split_credentials_leaves_ssh_and_local_paths_alone():
    assert gitio.split_credentials("git@github.com:org/repo.git")[1] is None
    assert gitio.split_credentials("/srv/kb-hub")[1] is None


def test_credential_env_carries_the_token_out_of_argv():
    env = gitio.credential_env(STRIPPED, "ghs_SECRETTOKEN")
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == f"http.{STRIPPED}.extraheader"
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
    assert "ghs_SECRETTOKEN" not in env["GIT_CONFIG_KEY_0"]


def test_credential_env_is_empty_without_a_token():
    assert gitio.credential_env(STRIPPED, None) == {}


def test_clone_persists_no_credential_in_git_config(tmp_path, run_git):
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    seed = tmp_path / "seed"
    seed.mkdir()
    run_git(tmp_path, "init", str(seed))
    (seed / "f.txt").write_text("x\n", encoding="utf-8")
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "seed")
    run_git(seed, "remote", "add", "origin", str(origin))
    run_git(seed, "push", "-u", "origin", "HEAD")

    dest = tmp_path / "clone"
    gitio.clone(str(origin), dest)
    config = (dest / ".git" / "config").read_text(encoding="utf-8")
    assert "x-access-token" not in config


def test_cache_key_survives_a_token_rotation(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    key_a = hub_mod.cache_key(CRED)
    key_b = hub_mod.cache_key(
        "https://x-access-token:ghs_ROTATED@github.com/org/kb-hub.git"
    )
    assert key_a == key_b
    assert key_a == hashlib.sha1(STRIPPED.encode("utf-8")).hexdigest()[:12]


@pytest.mark.skipif(
    not hasattr(__import__("os"), "geteuid"), reason="POSIX mode bits only"
)
def test_cache_directory_is_private(tmp_path, monkeypatch):
    import stat

    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    base = hub_mod.ensure_cache_base()
    assert stat.S_IMODE(base.stat().st_mode) == 0o700


def test_legacy_cache_with_a_credentialed_remote_is_rewritten(tmp_path, run_git):
    clone = tmp_path / "legacy"
    clone.mkdir()
    run_git(tmp_path, "init", str(clone))
    run_git(clone, "remote", "add", "origin", CRED)
    hub_mod.strip_remote_credentials(clone)
    assert gitio.remote_url(clone) == STRIPPED


def test_doctor_reports_a_clone_whose_credential_could_not_be_stripped(
    hub_worktree, git_kb, run_git
):
    """The rewrite is best-effort -- a read-only .git/config, or a remote
    named something other than origin, leaves the token in place. An operator
    has to be told, because the file is the thing that needs rotating."""
    from center_kb.doctor import check_hub
    from center_kb.hub import HubHandle

    run_git(hub_worktree, "remote", "add", "upstream", CRED)
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    assert any(
        "credential" in i.message and i.level == "warning" for i in issues
    )
    assert not any("ghs_SECRETTOKEN" in i.message for i in issues)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_hub_credentials.py -q`
Expected: FAIL — `gitio.split_credentials`, `hub.cache_key`, `hub.ensure_cache_base` and `hub.strip_remote_credentials` do not exist.

- [ ] **Step 3: Write the implementation**

In `src/center_kb/gitio.py`, add near `redact_url`:

```python
_URL_CRED_SPLIT_RE = re.compile(r"^(?P<scheme>\w+://)(?P<cred>[^@/\s]+)@(?P<rest>.*)$")


def split_credentials(url: str) -> tuple[str, str | None]:
    """(url without credentials, token) -- (url, None) when there are none.

    The CI templates hand us https://x-access-token:<token>@host/org/repo.git.
    Cloning that verbatim writes the token into <clone>/.git/config at mode
    0644, where it outlives the process and every token rotation.
    """
    m = _URL_CRED_SPLIT_RE.match(url or "")
    if not m:
        return url, None
    cred = m.group("cred")
    token = cred.split(":", 1)[1] if ":" in cred else cred
    return f"{m.group('scheme')}{m.group('rest')}", token or None


def credential_env(url: str, token: str | None) -> dict[str, str]:
    """Environment that hands git a credential without putting it in argv.

    /proc/<pid>/cmdline is world-readable; /proc/<pid>/environ is readable
    only by the same uid. GIT_CONFIG_COUNT/KEY/VALUE needs git >= 2.31.
    """
    if not token:
        return {}
    import base64

    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"http.{url}.extraheader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
    }


def _run_env(root: Path | None, env_extra: dict[str, str], *args: str):
    import os

    env = {**os.environ, **env_extra} if env_extra else None
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env,
    )
```

Replace `clone` and `pull`:

```python
def clone(url: str, dest: Path) -> None:
    """Clone `url` into `dest` with no credential and no CRLF rewriting.

    core.autocrlf=false / core.eol=lf are set on the command AND written into
    the clone's local config: with Git for Windows' default autocrlf=true a
    fresh checkout writes CRLF, hashsync hashes raw bytes, and the next
    publish looks like a whole-tree change (F-D10).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    stripped, token = split_credentials(url)
    proc = _run_env(
        None,
        credential_env(stripped, token),
        "-c", "core.autocrlf=false", "-c", "core.eol=lf",
        "clone", stripped, str(dest),
    )
    if proc.returncode != 0:
        raise GitError(redact_url(f"clone '{stripped}' failed: {proc.stderr.strip()}"))
    neutralize_line_endings(dest)


def pull(root: Path, url: str | None = None) -> None:
    stripped, token = split_credentials(url or remote_url(root))
    proc = _run_env(root, credential_env(stripped, token), "pull", "--ff-only")
    if proc.returncode != 0:
        raise GitError(redact_url(f"pull failed: {proc.stderr.strip()}"))
```

Add the push helper, replacing `intake`'s token-in-argv path:

```python
def push_branch_with_token(root: Path, url: str, token: str, branch: str) -> None:
    """Force-push `branch` to `url` with the token passed through the env.

    Replaces building https://x-access-token:<token>@... and handing it to
    git as an argv, where any local user could read it from
    /proc/<pid>/cmdline.
    """
    stripped, embedded = split_credentials(url)
    proc = _run_env(
        root,
        credential_env(stripped, token or embedded),
        "push", "--force", stripped, f"{branch}:{branch}",
    )
    if proc.returncode != 0:
        detail = redact_url(proc.stderr.strip().replace(stripped, "<hub-url>"))
        raise GitError(f"push branch '{branch}' failed: {detail}")
```

Move `_neutralize_line_endings` out of `intake.py:227-247` into `gitio.py` as `neutralize_line_endings(root: Path) -> None` (same body, using `_run(root, "config", key, value)`), and leave `intake._neutralize_line_endings = gitio.neutralize_line_endings` as an alias so the existing intake call site keeps working until Task 12 updates it.

In `src/center_kb/hub.py`:

```python
def cache_key(hub: str) -> str:
    """Cache directory name for a hub ref, derived from the credential-free URL.

    Keying on the credentialed URL stranded the old clone -- with the old
    token inside it -- on every rotation.
    """
    stripped, _ = gitio.split_credentials(hub)
    return hashlib.sha1(stripped.encode("utf-8")).hexdigest()[:12]


def ensure_cache_base() -> Path:
    base = _cache_base()
    base.mkdir(parents=True, exist_ok=True)
    try:
        base.chmod(0o700)  # no-op on Windows, which ignores POSIX mode bits
    except OSError:  # pragma: no cover - exotic filesystems
        logger.debug("could not restrict %s to 0700", base)
    return base


def strip_remote_credentials(root: Path) -> None:
    """Rewrite a cached clone's origin URL to its credential-free form."""
    current = gitio.remote_url(root)
    stripped, token = gitio.split_credentials(current)
    if token is None:
        return
    gitio._run(root, "remote", "set-url", "origin", stripped)
```

In `src/center_kb/doctor.py`'s `check_hub`, next to the existing hub checks:

```python
    for line in gitio._run(
        handle.root, "config", "--get-regexp", r"^remote\..*\.url$"
    ).stdout.splitlines():
        name, _, url = line.partition(" ")
        if gitio.split_credentials(url)[1] is not None:
            issues.append(
                Issue(
                    "warning",
                    f"the hub clone at {handle.root} still stores a credential "
                    f"in .git/config ({name}) -- an older version wrote it "
                    "there; rotate that token, then remove the clone so it is "
                    "re-created without one",
                )
            )
```

The URL itself is never put in the message -- `gitio.redact_url` exists for
that, and here the config key alone is enough to find it.

In `resolve_hub`, replace `cache = _cache_base() / hashlib.sha1(...)` with:

```python
    cache = ensure_cache_base() / cache_key(hub)
```

and call `strip_remote_credentials(cache)` immediately after a successful `clone` and at the top of the existing-cache branch, before `gitio.pull(cache)`. Pass the original `hub` ref to `pull` so the credential is available: `gitio.pull(cache, hub)`.

In `src/center_kb/intake.py`, replace the push block:

```python
                if cfg.push_via_token_url:
                    gitio.push_branch_with_token(
                        worktree, f"https://github.com/{hub_full}.git", token, branch
                    )
                else:
                    gitio.push_branch(worktree, branch)
```

(`worktree` is `handle.root` until Task 14 introduces the worktree; use `handle.root` here and Task 14 renames it.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_hub_credentials.py tests/test_gitio.py tests/test_hub.py tests/test_intake_publish.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/gitio.py src/center_kb/hub.py src/center_kb/intake.py tests/test_hub_credentials.py
git commit -m "fix(hub): keep hub credentials out of .git/config and out of argv (F-D7)"
```

---

### Task 12: CRLF — a fresh clone must not rewrite the mirror

Closes F-D10.

**Files:**
- Modify: `src/center_kb/publish.py` — `publish()` and `publish_federation()`
- Modify: `src/center_kb/intake.py` — use `gitio.neutralize_line_endings`
- Create: `src/center_kb/templates/init/gitattributes.txt`
- Modify: `src/center_kb/initcmd.py` — `HUB_TEMPLATES` and `CHILD_TEMPLATES`
- Test: `tests/test_publish_crlf.py` (new), `tests/test_init.py`

**Interfaces:**
- Consumes: `gitio.neutralize_line_endings` (Task 11).
- Produces: `.gitattributes` in the hub and child scaffolds.

- [ ] **Step 1: Write the failing test**

Create `tests/test_publish_crlf.py`:

```python
import subprocess

from center_kb.publish import publish


def test_second_publish_is_a_no_op_under_global_autocrlf(
    git_kb, tmp_path, run_git, monkeypatch
):
    """Reviewer D's F-D10: with Git for Windows' default core.autocrlf=true, a
    fresh hub checkout writes CRLF, hashsync hashes raw bytes, and every file
    looks changed -- one spurious whole-tree commit per fresh cache clone."""
    origin = tmp_path / "hub-origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    seed = tmp_path / "hub-seed"
    (seed / ".kb").mkdir(parents=True)
    (seed / "federation").mkdir()
    (seed / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8", newline="\n")
    (seed / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    run_git(tmp_path, "init", str(seed))
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "hub v0")
    run_git(seed, "remote", "add", "origin", str(origin))
    run_git(seed, "push", "-u", "origin", "HEAD")

    cache = tmp_path / "cache"
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(cache))
    # Simulate the Windows default without touching the runner's real config.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "global.gitconfig"))
    subprocess.run(
        ["git", "config", "--global", "core.autocrlf", "true"], check=True
    )

    publish(git_kb["kb"], str(origin), repo_id="child", mode="direct")
    head_after_first = run_git(origin, "rev-parse", "HEAD")
    publish(git_kb["kb"], str(origin), repo_id="child", mode="direct")
    assert run_git(origin, "rev-parse", "HEAD") == head_after_first
```

Append to `tests/test_init.py`:

```python
def test_hub_and_child_scaffolds_pin_lf_line_endings(tmp_path):
    from center_kb import initcmd

    for kind in ("hub", "child"):
        dest = tmp_path / kind
        dest.mkdir()
        initcmd.init_repo(dest, kind)
        text = (dest / ".gitattributes").read_text(encoding="utf-8")
        assert "* text=auto eol=lf" in text
```

`init_repo(target, kind, force=False, assets=None)` takes no `repo_id`: it derives one from `target.resolve().name`, which is why these tests name the directory rather than passing an id.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_publish_crlf.py tests/test_init.py -q -k "crlf or lf_line_endings"`
Expected: FAIL — the second publish moves the hub HEAD, and there is no `.gitattributes` template.

- [ ] **Step 3: Write the implementation**

In `src/center_kb/publish.py`, in both `publish()` and `publish_federation()`, add the CRLF call next to the existing excludes call:

```python
    _neutralize_excludes(handle.root)
    gitio.neutralize_line_endings(handle.root)
```

In `src/center_kb/intake.py`, replace the local `_neutralize_line_endings` definition and its call site with `gitio.neutralize_line_endings(handle.root)`, deleting the now-duplicated function.

Create `src/center_kb/templates/init/gitattributes.txt`:

```
# The hub mirror is hashed byte-for-byte (hashsync), so a checkout that
# rewrites LF to CRLF makes every file look changed: a spurious whole-tree
# commit per fresh clone, and a PR that asks an SME to review every file.
* text=auto eol=lf
*.png binary
*.webp binary
```

In `src/center_kb/initcmd.py`, add `".gitattributes": "gitattributes.txt"` to both `HUB_TEMPLATES` and `CHILD_TEMPLATES`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_publish_crlf.py tests/test_init.py tests/test_templates.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/publish.py src/center_kb/intake.py src/center_kb/initcmd.py src/center_kb/templates/init/gitattributes.txt tests/test_publish_crlf.py tests/test_init.py
git commit -m "fix(publish): neutralise CRLF so a fresh hub clone is not a whole-tree diff (F-D10)"
```

---

### Task 13: `gitio` worktree primitives

Groundwork for F-D3/F-D4. No behaviour change yet.

**Files:**
- Modify: `src/center_kb/gitio.py`
- Test: `tests/test_gitio.py`

**Interfaces:**
- Consumes: `gitio._run` (existing).
- Produces: `gitio.worktree_add(root: Path, path: Path, branch: str, base: str, reset: bool) -> None`, `gitio.worktree_remove(root: Path, path: Path) -> None`, `gitio.worktree_prune(root: Path) -> None`, `gitio.default_branch(root: Path) -> str`, `gitio.path_exists_at(root: Path, rev: str, relpath: str) -> bool`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gitio.py`:

```python
def test_worktree_add_and_remove_leave_the_main_tree_on_its_branch(tmp_path, run_git):
    from center_kb import gitio

    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(tmp_path, "init", str(repo))
    (repo / "f.txt").write_text("v1\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "v1")
    base = gitio.current_branch(repo)

    wt = tmp_path / "wt"
    gitio.worktree_add(repo, wt, "publish/alpha", base, reset=True)
    assert (wt / "f.txt").is_file()
    assert gitio.current_branch(wt) == "publish/alpha"
    assert gitio.current_branch(repo) == base

    (wt / "f.txt").write_text("v2\n", encoding="utf-8")
    run_git(wt, "add", "-A")
    run_git(wt, "commit", "-m", "v2")
    assert (repo / "f.txt").read_text(encoding="utf-8") == "v1\n"

    gitio.worktree_remove(repo, wt)
    assert not wt.exists()
    assert gitio.rev_exists(repo, "publish/alpha")


def test_worktree_add_can_reuse_an_existing_branch(tmp_path, run_git):
    from center_kb import gitio

    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(tmp_path, "init", str(repo))
    (repo / "f.txt").write_text("v1\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "v1")
    base = gitio.current_branch(repo)
    run_git(repo, "branch", "publish/alpha")

    wt = tmp_path / "wt"
    gitio.worktree_add(repo, wt, "publish/alpha", base, reset=False)
    assert gitio.current_branch(wt) == "publish/alpha"
    gitio.worktree_remove(repo, wt)


def test_worktree_prune_forgets_a_deleted_worktree(tmp_path, run_git):
    import shutil

    from center_kb import gitio

    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(tmp_path, "init", str(repo))
    (repo / "f.txt").write_text("v1\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "v1")
    wt = tmp_path / "wt"
    gitio.worktree_add(repo, wt, "publish/alpha", gitio.current_branch(repo), reset=True)
    shutil.rmtree(wt)  # simulate a crashed publish
    gitio.worktree_prune(repo)
    assert "wt" not in run_git(repo, "worktree", "list")


def test_default_branch_and_path_exists_at(tmp_path, run_git):
    from center_kb import gitio

    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(tmp_path, "init", str(repo))
    (repo / "federation").mkdir()
    (repo / "federation" / "alpha.txt").write_text("x\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "v1")
    branch = gitio.default_branch(repo)
    assert branch == gitio.current_branch(repo)
    assert gitio.path_exists_at(repo, branch, "federation/alpha.txt") is True
    assert gitio.path_exists_at(repo, branch, "federation/beta.txt") is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_gitio.py -q -k worktree`
Expected: FAIL — `AttributeError: module 'center_kb.gitio' has no attribute 'worktree_add'`

- [ ] **Step 3: Write the implementation**

Append to `src/center_kb/gitio.py`:

```python
def worktree_add(
    root: Path, path: Path, branch: str, base: str, reset: bool
) -> None:
    """Check `branch` out into its own working tree at `path`.

    reset=True recreates the branch at `base` (`-B`); reset=False attaches to
    the branch as it stands. Either way the repo's own working tree keeps its
    branch and its files -- which is the point: the intake server serves from
    that tree while a publish writes here.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    args = ["worktree", "add"]
    args += ["-B", branch, str(path), base] if reset else [str(path), branch]
    proc = _run(root, *args)
    if proc.returncode != 0:
        raise GitError(f"worktree add '{branch}' failed: {proc.stderr.strip()}")


def worktree_remove(root: Path, path: Path) -> None:
    """Remove a worktree; best-effort, so a cleanup failure never masks the
    real error a caller is already unwinding from."""
    proc = _run(root, "worktree", "remove", "--force", str(path))
    if proc.returncode != 0:
        import shutil

        shutil.rmtree(path, ignore_errors=True)
        _run(root, "worktree", "prune")


def worktree_prune(root: Path) -> None:
    """Forget worktrees whose directories are gone (crash cleanup)."""
    _run(root, "worktree", "prune")


def default_branch(root: Path) -> str:
    """origin/HEAD's branch when there is a remote, else the current branch."""
    proc = _run(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip().split("/", 1)[-1]
    return current_branch(root)


def path_exists_at(root: Path, rev: str, relpath: str) -> bool:
    """Does `relpath` exist in the tree at `rev`?

    Asks git rather than the working tree, so the answer does not depend on
    which branch some other publish left checked out.
    """
    return _run(root, "cat-file", "-e", f"{rev}:{relpath}").returncode == 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_gitio.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/gitio.py tests/test_gitio.py
git commit -m "feat(gitio): worktree primitives and ref-based tree queries (F-D3, F-D4)"
```

---

### Task 14: the intake writes in its own worktree

Closes F-D3 and F-D4 — the two HIGH intake findings.

**Files:**
- Modify: `src/center_kb/intake.py:265-409` (`intake_publish`)
- Test: `tests/test_intake_concurrency.py` (new), `tests/test_read_during_publish.py` (new)

**Interfaces:**
- Consumes: `gitio.worktree_add/remove/prune`, `gitio.default_branch`, `gitio.path_exists_at` (Task 13); `gitio.push_branch_with_token` (Task 11).
- Produces: `intake._hub_write_lock` (a module-level `threading.Lock`). `intake_publish`'s signature is unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/test_intake_concurrency.py`:

```python
"""Reviewer D's F-D4: two intake publishes for different repo-ids shared one
working tree, so beta's PR was based on publish/alpha and carried alpha's
unreviewed content -- and the clone stayed on publish/alpha for good."""
import threading
import time

from center_kb import gitio, intake


def test_two_repo_ids_publishing_together_do_not_cross_contaminate(
    intake_cfg, hub_worktree, make_upload
):
    calls = []

    def slow_create_pr(hub_full, token, branch, title, body, base, http=None):
        time.sleep(0.5)
        calls.append({"branch": branch, "base": base, "title": title})
        return f"https://github.com/{hub_full}/pull/1"

    intake_cfg.pr_hook = slow_create_pr  # see the fixture note below
    results = {}

    def run(rid):
        results[rid] = intake.intake_publish(
            intake_cfg, rid, f"c{rid}", f"org/{rid}", [], make_upload(rid)
        )

    t1 = threading.Thread(target=run, args=("alpha",))
    t2 = threading.Thread(target=run, args=("beta",))
    t1.start()
    time.sleep(0.3)
    t2.start()
    t1.join()
    t2.join()

    bases = {c["branch"]: c["base"] for c in calls}
    default = gitio.default_branch(hub_worktree)
    assert bases["publish/alpha"] == default
    assert bases["publish/beta"] == default

    beta_tree = gitio._run(
        hub_worktree, "ls-tree", "-r", "--name-only", "publish/beta"
    ).stdout
    assert "federation/beta/" in beta_tree
    assert "federation/alpha/" not in beta_tree

    assert gitio.current_branch(hub_worktree) == default


def test_no_worktree_is_left_behind(intake_cfg, hub_worktree, make_upload):
    intake.intake_publish(intake_cfg, "alpha", "c1", "org/alpha", [], make_upload("alpha"))
    listing = gitio._run(hub_worktree, "worktree", "list").stdout
    assert listing.strip().count("\n") == 0  # only the main worktree
```

Create `tests/test_read_during_publish.py`:

```python
"""Reviewer D's F-D3: while a publish was in flight, the read side served the
unmerged publish/<rid> branch."""
import threading
import time

from center_kb import gitio, intake


def test_the_serving_tree_never_shows_unmerged_content(
    intake_cfg, hub_worktree, make_upload
):
    seen = []

    def slow_create_pr(hub_full, token, branch, title, body, base, http=None):
        for _ in range(5):
            entry = hub_worktree / "federation" / "alpha"
            seen.append(entry.exists())
            seen.append(gitio.current_branch(hub_worktree))
            time.sleep(0.1)
        return f"https://github.com/{hub_full}/pull/1"

    intake_cfg.pr_hook = slow_create_pr
    default = gitio.default_branch(hub_worktree)
    t = threading.Thread(
        target=intake.intake_publish,
        args=(intake_cfg, "alpha", "c1", "org/alpha", [], make_upload("alpha")),
    )
    t.start()
    t.join()

    assert all(b == default for b in seen if isinstance(b, str))
    assert not any(b for b in seen if isinstance(b, bool))
```

Both tests need two fixtures. Add them to `tests/conftest.py`:

```python
@pytest.fixture
def make_upload(tmp_path):
    """A .tar.gz holding a minimal one-doc KB for a given repo-id."""
    import io
    import tarfile

    def _make(rid: str) -> bytes:
        buf = io.BytesIO()
        files = {
            "index.yaml": f"docs:\n  - id: {rid}-doc\n    title: {rid}\n    tags: []\n",
            f"{rid}-doc/_manifest.yaml": (
                f"id: {rid}-doc\ntitle: {rid}\nrevision: r1\nsections:\n"
                "  - id: '1.1'\n    title: One\n    summary: s\n"
                "    status: reviewed\n    file: ch1\n"
            ),
            f"{rid}-doc/ch1.md": f"## 1.1 One\n\n{rid} condensed.\n",
            f"{rid}-doc/ch1.raw.md": f"## 1.1 One\n\n{rid} verbatim.\n",
        }
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for name, text in files.items():
                data = text.encode("utf-8")
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    return _make
```

`intake_cfg` already exists in `tests/test_intake_publish.py`; move it into `tests/conftest.py` unchanged so three test modules can share it, and give `IntakeConfig` a `pr_hook` test seam in Step 3.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_intake_concurrency.py tests/test_read_during_publish.py -q`
Expected: FAIL — beta's base is `publish/alpha`, beta's tree carries `federation/alpha/`, and the hub is left on `publish/alpha`.

- [ ] **Step 3: Write the implementation**

In `src/center_kb/intake.py`, add the lock and the test seam:

```python
# One hub, one set of refs: worktree add/remove and the ref updates around it
# are serialised process-wide. repo_lock(rid) still owns same-rid
# idempotence; this owns the shared repository state underneath it.
_hub_write_lock = threading.Lock()
```

Add `pr_hook: object = None  # test seam -- None = ghapp.create_or_get_pr` to `IntakeConfig`.

Rewrite the body of `intake_publish` from `with repo_lock(rid):` down. The shape:

```python
    with repo_lock(rid):
        handle = _resolve_hub_or_503(cfg.hub_ref)
        _dest_for_rid(handle.federation_dir, rid)  # validate before any write
        publish_mod._neutralize_excludes(handle.root)
        gitio.neutralize_line_endings(handle.root)
        try:
            gitio.pull(handle.root, cfg.hub_ref)
        except gitio.GitError:
            logger.warning("hub pull failed -- publishing against cached main")
        # The base is a ref, never the serving tree's current branch: reading
        # current_branch() is what made a concurrent publish's branch become
        # beta's PR base, and left the tree on publish/alpha for good.
        base = gitio.default_branch(handle.root)
        branch = f"publish/{rid}"
        dest_on_main = gitio.path_exists_at(handle.root, base, f"federation/{rid}")
        reset = dest_on_main or not gitio.rev_exists(handle.root, branch)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_kb = Path(tmp) / "kb"
            tmp_kb.mkdir()
            safe_extract(archive, tmp_kb, cfg.max_tar_bytes)
            work = Path(tmp) / "hub"
            with _hub_write_lock:
                gitio.worktree_prune(handle.root)
                gitio.worktree_add(handle.root, work, branch, base, reset=reset)
            try:
                return _publish_in_worktree(
                    cfg, handle, work, rid, branch, base,
                    source_commit, source_repo_full, deletes, tmp_kb, store, http,
                )
            finally:
                with _hub_write_lock:
                    gitio.worktree_remove(handle.root, work)
```

Extract everything that used to run between the checkout and the `finally` into a module-level `_publish_in_worktree(...)`. It is the existing body with three substitutions:

- `dest` becomes `work / "federation" / rid` (the worktree's copy, not the serving tree's);
- every `gitio._run(handle.root, ...)`, `gitio.commit_paths(handle.root, ...)` and `federation.write_federation_index(handle.federation_dir)` becomes the `work`-rooted equivalent (`work / "federation"` for the index);
- the PR call takes `base=base` — the default branch — and goes through the seam:

```python
                create_pr = cfg.pr_hook or ghapp.create_or_get_pr
                return create_pr(
                    hub_full,
                    token,
                    branch,
                    title=f"publish: {rid} @ {source_commit}",
                    body=publish_mod.PR_BODY_TEMPLATE.format(
                        rid=rid, commit=source_commit
                    ),
                    base=base,
                    http=http,
                )
```

Keep the `hashsync.HashSyncError` and `assetstore.AssetStoreError` restore paths, retargeted at `work`. There is no `finally: gitio.checkout(...)` any more — removing the worktree is the whole cleanup.

Keeping `_publish_in_worktree` a module-level function (not a closure) keeps `intake.py` under 800 lines and makes the worktree parameter explicit at every call.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_intake_concurrency.py tests/test_read_during_publish.py tests/test_intake_publish.py tests/test_intake_core.py tests/test_intake_http.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/intake.py tests/conftest.py tests/test_intake_concurrency.py tests/test_read_during_publish.py
git commit -m "fix(intake): one git worktree per publish, so the serving tree never moves (F-D3, F-D4)"
```

---

### Task 15: intake startup checks

The recovery path for a hub already stuck on `publish/<rid>` — F-D4's aftermath.

**Files:**
- Modify: `src/center_kb/web/app.py`
- Test: `tests/test_intake_startup.py` (new)

**Interfaces:**
- Consumes: `gitio.worktree_prune`, `gitio.default_branch`, `gitio.current_branch` (Task 13).
- Produces: `intake.check_serving_clone(handle) -> list[str]` — warning lines, empty when healthy.

- [ ] **Step 1: Write the failing test**

Create `tests/test_intake_startup.py`:

```python
from center_kb import gitio, intake
from center_kb.hub import HubHandle


def test_a_clone_left_on_a_publish_branch_is_reported(hub_worktree, run_git):
    run_git(hub_worktree, "checkout", "-b", "publish/alpha")
    warnings = intake.check_serving_clone(HubHandle(root=hub_worktree))
    assert any("publish/alpha" in w for w in warnings)
    assert any("git -C" in w for w in warnings)


def test_a_healthy_clone_reports_nothing(hub_worktree):
    assert intake.check_serving_clone(HubHandle(root=hub_worktree)) == []


def test_startup_prunes_a_stale_worktree(hub_worktree, tmp_path, run_git):
    import shutil

    wt = tmp_path / "stale"
    gitio.worktree_add(
        hub_worktree, wt, "publish/ghost", gitio.default_branch(hub_worktree), reset=True
    )
    shutil.rmtree(wt)
    intake.check_serving_clone(HubHandle(root=hub_worktree))
    assert "stale" not in gitio._run(hub_worktree, "worktree", "list").stdout
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_intake_startup.py -q`
Expected: FAIL — `AttributeError: module 'center_kb.intake' has no attribute 'check_serving_clone'`

- [ ] **Step 3: Write the implementation**

Add to `src/center_kb/intake.py`:

```python
def check_serving_clone(handle: hub_mod.HubHandle) -> list[str]:
    """Warning lines about a hub clone that is not fit to serve from.

    Before the worktree change, a crashed or concurrent publish could leave
    the clone checked out on publish/<rid> permanently -- and the read side
    then served that unmerged branch until someone fixed it by hand. This is
    how an operator finds out.
    """
    gitio.worktree_prune(handle.root)
    warnings: list[str] = []
    try:
        current = gitio.current_branch(handle.root)
        default = gitio.default_branch(handle.root)
    except gitio.GitError as exc:
        return [f"could not read the hub clone's branch: {exc}"]
    if current != default:
        warnings.append(
            f"the hub clone at {handle.root} is on branch '{current}', not "
            f"'{default}' -- it is serving content that may not be merged; fix "
            f"with: git -C {handle.root} checkout {default}"
        )
    return warnings
```

In `src/center_kb/web/app.py`, call it where the app resolves its hub at startup and log each line at `warning` level:

```python
    handle = hub_mod.resolve_hub(hub_ref)
    if handle is not None:
        for line in intake.check_serving_clone(handle):
            logger.warning("%s", line)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_intake_startup.py tests/test_web_app.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/intake.py src/center_kb/web/app.py tests/test_intake_startup.py
git commit -m "feat(intake): report a serving clone stuck off the default branch (F-D4)"
```

---

### Task 16: bounded uploads and a rate limiter that survives a proxy

Closes F-D12.

**Files:**
- Modify: `src/center_kb/web/intake_routes.py:87-119`
- Modify: `src/center_kb/web/ratelimit.py`
- Test: `tests/test_intake_http.py`

**Interfaces:**
- Consumes: `intake.IntakeError` (existing).
- Produces: `intake_routes.read_capped(upload, max_bytes) -> bytes`; `ratelimit.client_key(request, trusted_proxies: int) -> str`; `IntakeConfig.trusted_proxies: int = 0`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intake_http.py`:

```python
def test_oversized_upload_is_refused_without_buffering_the_whole_body(
    intake_client, intake_cfg
):
    """F-D12: archive = await upload.read() buffered the entire body before
    safe_extract ever compared it to the cap."""
    intake_cfg.max_tar_bytes = 1024
    reads = []

    class CountingUpload:
        def __init__(self, data):
            self._buf = io.BytesIO(data)

        async def read(self, size=-1):
            chunk = self._buf.read(size if size and size > 0 else None)
            reads.append(len(chunk))
            return chunk

    from center_kb.web import intake_routes

    upload = CountingUpload(b"x" * (5 * 1024 * 1024))
    with pytest.raises(intake.IntakeError) as exc:
        asyncio.run(intake_routes.read_capped(upload, intake_cfg.max_tar_bytes))
    assert exc.value.status == 413
    assert sum(reads) < 5 * 1024 * 1024


def test_content_length_over_the_cap_is_refused_before_reading(intake_client, intake_cfg):
    intake_cfg.max_tar_bytes = 1024
    resp = intake_client.post(
        "/intake/publish",
        headers={"authorization": "Bearer t", "content-length": str(10 * 1024 * 1024)},
    )
    assert resp.status_code == 413


def test_forwarded_for_is_ignored_by_default():
    from center_kb.web import ratelimit

    request = _fake_request(client_host="10.0.0.1", xff="1.2.3.4, 10.0.0.9")
    assert ratelimit.client_key(request, trusted_proxies=0) == "10.0.0.1"


def test_forwarded_for_is_honoured_behind_a_declared_proxy():
    from center_kb.web import ratelimit

    request = _fake_request(client_host="10.0.0.1", xff="1.2.3.4, 10.0.0.9")
    assert ratelimit.client_key(request, trusted_proxies=1) == "1.2.3.4"


def test_forwarded_for_shorter_than_the_proxy_chain_falls_back_to_the_peer():
    from center_kb.web import ratelimit

    request = _fake_request(client_host="10.0.0.1", xff="1.2.3.4")
    assert ratelimit.client_key(request, trusted_proxies=3) == "10.0.0.1"
```

Add the small helper the three limiter tests use, at the top of `tests/test_intake_http.py`:

```python
class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, client_host, xff):
        self.client = _FakeClient(client_host)
        self.headers = {"x-forwarded-for": xff} if xff else {}


def _fake_request(client_host, xff=""):
    return _FakeRequest(client_host, xff)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_intake_http.py -q -k "oversized or content_length or forwarded"`
Expected: FAIL — `read_capped` and `client_key` do not exist.

- [ ] **Step 3: Write the implementation**

Add to `src/center_kb/web/ratelimit.py`:

```python
def client_key(request, trusted_proxies: int = 0) -> str:
    """The rate-limit key for a request.

    trusted_proxies=0 (the default) keys on the socket peer and ignores
    X-Forwarded-For entirely, so the key cannot be spoofed. When an operator
    declares N trusted proxies in front of the server, the client is the
    N-th entry from the right of X-Forwarded-For -- the last hop the trusted
    chain did not write. A header shorter than the declared chain is not
    trustworthy, so it falls back to the peer.
    """
    peer = request.client.host if request.client else "unknown"
    if trusted_proxies <= 0:
        return peer
    raw = request.headers.get("x-forwarded-for", "")
    hops = [h.strip() for h in raw.split(",") if h.strip()]
    if len(hops) < trusted_proxies:
        return peer
    return hops[-trusted_proxies]
```

In `src/center_kb/intake.py`, add `trusted_proxies: int = 0` to `IntakeConfig`, and read it in `intake_config_from_env`:

```python
    try:
        trusted_proxies = int(os.environ.get("CENTER_KB_TRUSTED_PROXIES", "0"))
    except ValueError:
        trusted_proxies = 0
```

passing `trusted_proxies=trusted_proxies` into the returned `IntakeConfig`.

In `src/center_kb/web/intake_routes.py`, add the capped reader and use both:

```python
_CHUNK = 64 * 1024


async def read_capped(upload, max_bytes: int) -> bytes:
    """Read an upload in chunks, aborting at the cap.

    `await upload.read()` buffered the whole body first -- Starlette applies
    no default multipart size limit -- so a 413 cost as much memory as the
    body an allowlisted child chose to send.
    """
    buf = bytearray()
    while True:
        chunk = await upload.read(_CHUNK)
        if not chunk:
            return bytes(buf)
        buf += chunk
        if len(buf) > max_bytes:
            raise intake.IntakeError(413, f"archive exceeds {max_bytes} bytes")
```

In `publish()`, replace the client-IP line and the read:

```python
        client_ip = client_key(request, getattr(cfg, "trusted_proxies", 0))
```

```python
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > cfg.max_tar_bytes:
                raise intake.IntakeError(
                    413, f"archive exceeds {cfg.max_tar_bytes} bytes"
                )
            archive = await read_capped(upload, cfg.max_tar_bytes)
```

adding `client_key` to the existing `from center_kb.web.ratelimit import (...)` block.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_intake_http.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/web/intake_routes.py src/center_kb/web/ratelimit.py src/center_kb/intake.py tests/test_intake_http.py
git commit -m "fix(intake): cap uploads before buffering, key the limiter correctly behind a proxy (F-D12)"
```

---

### Task 17: tighter claim checks and an optional workflow pin

Closes F-D16.

**Files:**
- Modify: `src/center_kb/models.py:102-105` (`Registry`)
- Modify: `src/center_kb/federation.py` (`registry_map`)
- Modify: `src/center_kb/intake.py` (`authorize`)
- Test: `tests/test_intake_core.py`, `tests/test_federation_registry.py`

**Interfaces:**
- Consumes: `federation.registry_map` (Task 6).
- Produces: `models.RegistryEntry` (fields `repo_id: str`, `workflow: str = ""`); `models.Registry.resolve(repo: str) -> RegistryEntry | None`. `federation.registry_map` keeps returning `dict[str, str]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_federation_registry.py`:

```python
def test_registry_accepts_the_plain_string_form(tmp_path):
    import yaml

    from center_kb import federation

    fed = tmp_path / "federation"
    fed.mkdir()
    (fed / "registry.yaml").write_text(
        yaml.safe_dump({"repos": {"org/repo": "rid"}}), encoding="utf-8", newline="\n"
    )
    reg = federation.load_registry(fed)
    assert reg.resolve("org/repo").repo_id == "rid"
    assert reg.resolve("org/repo").workflow == ""
    assert federation.registry_map(reg) == {"org/repo": "rid"}


def test_registry_accepts_the_mapping_form_with_a_workflow_pin(tmp_path):
    import yaml

    from center_kb import federation

    fed = tmp_path / "federation"
    fed.mkdir()
    (fed / "registry.yaml").write_text(
        yaml.safe_dump(
            {
                "repos": {
                    "org/repo": {
                        "repo_id": "rid",
                        "workflow": "org/repo/.github/workflows/kb-publish.yml@refs/heads/main",
                    }
                }
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    reg = federation.load_registry(fed)
    assert reg.resolve("org/repo").repo_id == "rid"
    assert reg.resolve("org/repo").workflow.endswith("@refs/heads/main")
    assert federation.registry_map(reg) == {"org/repo": "rid"}
```

Append to `tests/test_intake_core.py`:

```python
import pytest

from center_kb import intake, models


def _claims(**over):
    base = {
        "ref": "refs/tags/kb-publish/20260911-101500",
        "repository": "org/repo",
        "job_workflow_ref": "org/repo/.github/workflows/kb-publish.yml@refs/heads/main",
    }
    base.update(over)
    return base


PLAIN = models.Registry(repos={"org/repo": "rid"})


def test_a_normal_tag_ref_is_accepted():
    assert intake.authorize(_claims(), PLAIN) == "rid"


@pytest.mark.parametrize(
    "ref",
    [
        "refs/tags/kb-publish/../../heads/main",
        "refs/tags/kb-publish/a/../b",
        "refs/tags/kb-publishing/20260911",
        "refs/heads/main",
        "refs/tags/kb-publish/",
    ],
)
def test_ref_shapes_outside_the_tag_namespace_are_refused(ref):
    with pytest.raises(intake.IntakeError) as exc:
        intake.authorize(_claims(ref=ref), PLAIN)
    assert exc.value.status == 403


PINNED = models.Registry(
    repos={
        "org/repo": {
            "repo_id": "rid",
            "workflow": "org/repo/.github/workflows/kb-publish.yml@refs/heads/main",
        }
    }
)


def test_a_pinned_workflow_must_match():
    assert intake.authorize(_claims(), PINNED) == "rid"


def test_a_different_workflow_is_refused_when_pinned():
    with pytest.raises(intake.IntakeError) as exc:
        intake.authorize(
            _claims(job_workflow_ref="org/repo/.github/workflows/evil.yml@refs/heads/main"),
            PINNED,
        )
    assert exc.value.status == 403
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_intake_core.py tests/test_federation_registry.py -q`
Expected: FAIL — `Registry` has no `resolve`, the mapping form fails validation, and `ref="refs/tags/kb-publish/../../heads/main"` is accepted today.

- [ ] **Step 3: Write the implementation**

In `src/center_kb/models.py`, replace `Registry`:

```python
class RegistryEntry(BaseModel):
    """One allowlisted publisher: the repo-id it owns, and optionally the
    single workflow allowed to publish as it (the `job_workflow_ref` claim)."""

    repo_id: str
    workflow: str = ""


class Registry(BaseModel):
    """federation/registry.yaml -- allowlist: 'owner/repo' -> repo_id on the hub.

    A value may be the plain repo-id string (the documented default) or a
    mapping {repo_id, workflow}; both are read through `resolve`.
    """

    repos: dict[str, str | RegistryEntry] = Field(default_factory=dict)

    def resolve(self, repo: str) -> RegistryEntry | None:
        value = self.repos.get(repo)
        if value is None:
            return None
        if isinstance(value, RegistryEntry):
            return value
        return RegistryEntry(repo_id=value)
```

In `src/center_kb/federation.py`, update `registry_map` to flatten either form:

```python
def registry_map(registry: models.Registry) -> dict[str, str]:
    """{owner/repo: repo_id} -- the one accessor both write paths read through."""
    out: dict[str, str] = {}
    for repo in registry.repos:
        entry = registry.resolve(repo)
        if entry is not None:
            out[repo] = entry.repo_id
    return out
```

In `src/center_kb/intake.py`, rewrite `authorize`:

```python
_TAG_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def authorize(claims: dict, registry: models.Registry) -> str:
    """claims -> repo_id. The registry -- never the payload -- decides the path."""
    from center_kb.pubgate import normalize_repo_id, GateError

    ref = claims.get("ref", "")
    if not ref.startswith(TAG_REF_PREFIX):
        raise IntakeError(
            403, f"ref '{ref}' is not a {TAG_REF_PREFIX}* tag -- run `kb publish`"
        )
    # Exact segments, not a bare prefix: 'refs/tags/kb-publish/../../heads/main'
    # passes startswith() and is the shape that becomes a hole the moment the
    # ref namespace grows.
    tail = ref[len(TAG_REF_PREFIX):]
    segments = tail.split("/")
    if not tail or not all(_TAG_SEGMENT_RE.fullmatch(s) for s in segments):
        raise IntakeError(403, f"ref '{ref}' is not a well-formed publish tag")
    repo = claims.get("repository", "")
    entry = registry.resolve(repo)
    if entry is None or not entry.repo_id:
        raise IntakeError(
            403,
            f"repo '{repo}' is not registered -- open a PR on the hub adding "
            f"`{repo}: <repo-id>` under `repos:` in federation/registry.yaml",
        )
    if entry.workflow and claims.get("job_workflow_ref", "") != entry.workflow:
        raise IntakeError(
            403,
            f"repo '{repo}' is pinned to workflow '{entry.workflow}' in "
            "federation/registry.yaml, but this token was minted by "
            f"'{claims.get('job_workflow_ref', '')}'",
        )
    try:
        return normalize_repo_id(entry.repo_id)
    except GateError as exc:
        raise IntakeError(500, f"registry maps '{repo}' to an unusable repo-id: {exc}")
```

Add `import re` to `intake.py` if it is not already imported, and delete the now-unused `from center_kb.pubgate import REPO_ID_RE` line Task 6 left in `authorize`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_intake_core.py tests/test_federation_registry.py tests/test_intake_http.py tests/test_publish_registry.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/models.py src/center_kb/federation.py src/center_kb/intake.py tests/test_intake_core.py tests/test_federation_registry.py
git commit -m "fix(intake): exact ref segments and an optional workflow pin (F-D16)"
```

---

### Task 18: reject Windows path shapes in uploads

Closes F-D18.

**Files:**
- Modify: `src/center_kb/intake.py` — `safe_extract`, and the `deletes` guard in `intake_publish`
- Test: `tests/test_intake_core.py`

**Interfaces:**
- Consumes: `intake.IntakeError` (existing).
- Produces: `intake._reject_path_shape(label: str, rel: str) -> None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intake_core.py`:

```python
import io
import tarfile


def _tar_with(name: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"x\n"
        info = tarfile.TarInfo(name)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.mark.parametrize("name", ["C:evil.md", "C:/evil.md", "dir\\evil.md", "\\evil.md"])
def test_windows_path_shapes_in_a_tar_are_refused(name, tmp_path):
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_with(name), tmp_path)
    assert exc.value.status == 400


@pytest.mark.parametrize("rel", ["C:boom", "dir\\boom.md"])
def test_windows_path_shapes_in_deletes_are_refused(rel, intake_cfg):
    with pytest.raises(intake.IntakeError) as exc:
        intake.intake_publish(intake_cfg, "alpha", "c1", "org/alpha", [rel], b"")
    assert exc.value.status == 400
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_intake_core.py -q -k windows_path`
Expected: FAIL — `C:evil.md` and `dir\evil.md` are accepted (`Path.is_absolute()` is False for drive-relative paths, and a backslash is a plain character on POSIX).

- [ ] **Step 3: Write the implementation**

Add to `src/center_kb/intake.py`:

```python
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _reject_path_shape(label: str, rel: str) -> None:
    """Refuse Windows path shapes on every OS.

    Path.is_absolute() is False for a drive-relative 'C:evil.md', so _guard
    collapsed it into the destination on Windows; on Linux it created a file
    literally named 'C:evil.md' inside the published snapshot. A backslash is
    a separator on Windows and a legal filename character on POSIX -- neither
    belongs in a snapshot that both must read the same way.
    """
    if _DRIVE_RE.match(rel) or "\\" in rel:
        raise IntakeError(
            400, f"{label} '{rel}' uses a Windows path shape -- use posix paths"
        )
```

Call it in `safe_extract`, right after the `isreg()` check and before `rel = Path(member.name)`:

```python
            _reject_path_shape("tar member", member.name)
```

and in `intake_publish`'s deletes loop, before the existing escape check:

```python
    for rel in deletes:
        _reject_path_shape("delete path", rel)
        p = Path(rel)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_intake_core.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/intake.py tests/test_intake_core.py
git commit -m "fix(intake): refuse drive-relative and backslash paths on every OS (F-D18)"
```

---

### Task 19: verify asset bytes against their content-addressed name

Closes F-D11 item 1.

**Files:**
- Modify: `src/center_kb/assetstore.py`
- Modify: `src/center_kb/assetcmd.py:100-148` (`_entry_resolves`, `verify_assets`, `VerifyReport`)
- Modify: `src/center_kb/web/ui.py:465-480` (the store-hit cache fill)
- Test: `tests/test_assetstore.py`, `tests/test_assetcmd.py`, `tests/test_web_ui.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `assetstore.verify_bytes(name: str, data: bytes) -> bool`, `assetstore.get_verified(store, name: str) -> bytes | None`; `VerifyReport.corrupt: list[str]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_assetstore.py`:

```python
import hashlib

from center_kb import assetstore


def _named(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest() + ".png"


def test_verify_bytes_accepts_matching_content():
    data = b"real image bytes"
    assert assetstore.verify_bytes(_named(data), data) is True


def test_verify_bytes_rejects_tampered_content():
    data = b"real image bytes"
    assert assetstore.verify_bytes(_named(data), b"tampered") is False


def test_get_verified_refuses_a_tampered_object():
    data = b"real image bytes"
    name = _named(data)
    store = assetstore.MemoryStore()
    store.data[name] = b"tampered"
    with pytest.raises(assetstore.AssetStoreError, match="does not match its name"):
        assetstore.get_verified(store, name)


def test_get_verified_returns_a_clean_object():
    data = b"real image bytes"
    name = _named(data)
    store = assetstore.MemoryStore()
    store.put(name, data)
    assert assetstore.get_verified(store, name) == data


def test_get_verified_passes_a_miss_through():
    store = assetstore.MemoryStore()
    assert assetstore.get_verified(store, _named(b"absent")) is None
```

Append to `tests/test_assetcmd.py`:

```python
def test_verify_reports_a_tampered_object_as_not_ok(hub_worktree, run_git):
    import hashlib

    from center_kb import assetcmd, assetstore
    from center_kb.hub import HubHandle
    from tests.conftest import make_fed_entry

    data = b"real image bytes"
    name = hashlib.sha256(data).hexdigest() + ".png"
    entry = make_fed_entry(hub_worktree, "child")
    (entry / "doc" / "assets").mkdir(parents=True, exist_ok=True)
    store = assetstore.MemoryStore()
    store.data[name] = b"tampered"
    from center_kb import models

    models.save_yaml_model(
        entry / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc/assets/{name}"]),
    )
    report = assetcmd.verify_assets(HubHandle(root=hub_worktree), store=store)
    assert report.ok is False
    assert any(name in line for line in report.corrupt)
```

Append to `tests/test_web_ui.py`:

```python
def test_a_tampered_store_object_is_not_cached_or_served(ui_client_with_store):
    client, store, name = ui_client_with_store
    store.data[name] = b"tampered"
    resp = client.get(f"/assets/{name}")
    assert resp.status_code == 503
    from center_kb import hub as hub_mod

    assert not (hub_mod._cache_base() / "asset-cache" / name).exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_assetstore.py tests/test_assetcmd.py tests/test_web_ui.py -q -k "verify or tampered"`
Expected: FAIL — `assetstore.verify_bytes` does not exist, `verify_assets` returns `ok = True` for a tampered object, and the UI caches the wrong bytes for a year.

- [ ] **Step 3: Write the implementation**

Append to `src/center_kb/assetstore.py`:

```python
def verify_bytes(name: str, data: bytes) -> bool:
    """Do these bytes hash to the sha256 in this content-addressed filename?

    AssetsRecord's contract is that the filename's sha256 IS the content's
    sha256 -- synthesized_asset_entries takes the hash straight from the name
    without ever reading a byte. Nothing checked it, so one bad object in the
    store was served with `max-age=31536000, immutable` and cached on disk.
    """
    import hashlib

    m = _ASSET_NAME_RE.match(name)
    if not m:
        return False
    return hashlib.sha256(data).hexdigest() == m.group(1)


def get_verified(store, name: str):
    """store.get(name), refusing bytes that do not match the name."""
    data = store.get(name)
    if data is None:
        return None
    if not verify_bytes(name, data):
        raise AssetStoreError(
            f"asset '{name}' does not match its name -- the object store holds "
            "content whose sha256 differs from the content-addressed key"
        )
    return data
```

In `src/center_kb/assetcmd.py`, add `corrupt: list[str] = field(default_factory=list)` to `VerifyReport`, include it in `ok`:

```python
    @property
    def ok(self) -> bool:
        return not self.missing_records and not self.dangling_refs and not self.corrupt
```

and make the resolution check hash content:

```python
def _entry_resolves(rid_dir: Path, rel: str, store, corrupt: list[str]) -> bool:
    """Resolvable AND intact. `kb assets verify` used to call store.exists,
    which cannot tell a good object from a tampered one."""
    local = rid_dir / rel
    if local.is_file():
        if not assetstore.verify_bytes(Path(rel).name, local.read_bytes()):
            corrupt.append(f"{rid_dir.name}: {rel}")
        return True
    if store is None:
        return False
    try:
        return assetstore.get_verified(store, Path(rel).name) is not None
    except assetstore.AssetStoreError:
        corrupt.append(f"{rid_dir.name}: {rel}")
        return True
```

Update the caller in `verify_assets` to pass `report.corrupt`, and sort it alongside the other lists at the end.

In `src/center_kb/web/ui.py`'s `_find_asset`, replace `data = store.get(name)` with:

```python
            data = assetstore.get_verified(store, name)
```

The existing handler already turns `AssetStoreError` into a 503, and because the exception is raised before the write, nothing reaches the disk cache.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_assetstore.py tests/test_assetcmd.py tests/test_web_ui.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/assetstore.py src/center_kb/assetcmd.py src/center_kb/web/ui.py tests/test_assetstore.py tests/test_assetcmd.py tests/test_web_ui.py
git commit -m "fix(assets): hash-verify store bytes before caching or serving them (F-D11)"
```

---

### Task 20: asset records land on the leaf entry

Closes F-D11 item 2.

**Files:**
- Modify: `src/center_kb/assetcmd.py:44-48` (`_rid_dirs`)
- Test: `tests/test_assetcmd.py`

**Interfaces:**
- Consumes: `federation.iter_entry_dirs` (existing).
- Produces: `assetcmd._rid_dirs(handle) -> list[tuple[str, Path]]` — now `(entry_rel, path)` pairs.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_assetcmd.py`:

```python
def test_a_nested_entry_gets_its_record_at_the_leaf(hub_worktree):
    import hashlib

    from center_kb import assetcmd, assetstore
    from center_kb.hub import HubHandle
    from tests.conftest import make_fed_entry

    data = b"nested image"
    name = hashlib.sha256(data).hexdigest() + ".png"
    leaf = make_fed_entry(hub_worktree, "mid/deep")
    assets = leaf / "doc" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / name).write_bytes(data)

    store = assetstore.MemoryStore()
    assetcmd.migrate_assets(HubHandle(root=hub_worktree), store=store)

    assert (leaf / assetstore.RECORD_NAME).is_file()
    assert not (hub_worktree / "federation" / "mid" / assetstore.RECORD_NAME).exists()
    entries = assetstore.synthesized_asset_entries(leaf)
    assert entries == {f"doc/assets/{name}": hashlib.sha256(data).hexdigest()}
```

`make_fed_entry` must accept a nested id; if it does not already, extend it to `mkdir(parents=True)` on the entry path.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_assetcmd.py -q -k nested_entry`
Expected: FAIL — the record lands at `federation/mid/_assets.yaml` with the path `deep/doc/assets/<sha>.png`, so `synthesized_asset_entries(leaf)` is `{}`.

- [ ] **Step 3: Write the implementation**

In `src/center_kb/assetcmd.py`:

```python
def _rid_dirs(handle) -> list[tuple[str, Path]]:
    """(entry path-id, directory) for every LEAF entry under federation/.

    Iterating the top level treated `mid` as the repo for a nested entry
    `mid/deep`: the record landed at federation/mid/_assets.yaml with the
    path `deep/doc/assets/<sha>.png`, so the leaf every reader actually uses
    -- via federation.iter_entry_dirs -- had no record at all.
    """
    from center_kb import federation

    return federation.iter_entry_dirs(handle.federation_dir)
```

Update the three call sites to unpack the pair. In `migrate_assets`:

```python
    for entry_rel, rid_dir in _rid_dirs(handle):
        try:
            diverted = assetstore.divert_and_record(rid_dir, store)
        except assetstore.AssetStoreError:
            rel = f"federation/{entry_rel}"
            ...
        if diverted:
            report.per_rid[entry_rel] = len(diverted)
```

In `verify_assets`:

```python
    for entry_rel, rid_dir in _rid_dirs(handle):
        for rel in _record_entries(rid_dir):
            label = f"{entry_rel}: {rel}"
```

and pass `entry_rel` into `_entry_resolves`'s `corrupt` labels in place of `rid_dir.name`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_assetcmd.py tests/test_federation_nested.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/assetcmd.py tests/test_assetcmd.py tests/conftest.py
git commit -m "fix(assets): walk leaf entries, so nested records land where readers look (F-D11)"
```

---

### Task 21: hub-to-hub publish stops being asset-store-blind

Closes F-D11 item 3.

**Files:**
- Modify: `src/center_kb/publish.py` — `_snapshot_federation`
- Test: `tests/test_federation_nested.py`

**Interfaces:**
- Consumes: `assetstore.store_for_hub`, `assetstore.divert_and_record`, `assetstore.synthesized_asset_entries` (existing); `pubgate.split_allowlist` (Task 7).
- Produces: `_snapshot_federation` honours its `store` parameter.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_federation_nested.py`:

```python
def test_hub_to_hub_publish_carries_diverted_assets(
    hub_worktree, tmp_path, run_git
):
    """F-D11: _snapshot_federation declared store=None and never referenced it,
    so migrated assets looked deleted to the upstream hub."""
    import hashlib

    from center_kb import assetstore, models
    from center_kb.publish import publish_federation
    from tests.conftest import make_fed_entry

    data = b"mid tier image"
    name = hashlib.sha256(data).hexdigest() + ".png"
    leaf = make_fed_entry(hub_worktree, "child")
    models.save_yaml_model(
        leaf / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc/assets/{name}"]),
    )
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "mid: migrated assets")

    upstream = tmp_path / "root-hub"
    (upstream / ".kb").mkdir(parents=True)
    (upstream / "federation").mkdir()
    (upstream / ".kb" / "index.yaml").write_text(
        "docs: []\n", encoding="utf-8", newline="\n"
    )
    run_git(tmp_path, "init", str(upstream))
    run_git(upstream, "add", "-A")
    run_git(upstream, "commit", "-m", "root hub v0")

    store = assetstore.MemoryStore()
    store.put(name, data)
    publish_federation(
        hub_worktree / ".kb", str(upstream), repo_id="mid", mode="direct"
    )
    mirrored = upstream / "federation" / "mid" / "child" / assetstore.RECORD_NAME
    assert mirrored.is_file()
    record = models.load_yaml_model(mirrored, models.AssetsRecord)
    assert record.assets == [f"doc/assets/{name}"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_federation_nested.py -q -k diverted_assets`
Expected: FAIL — the record is not mirrored (`_assets.yaml` is not an allowlisted artefact, and `_snapshot_federation` never synthesizes entries for it).

- [ ] **Step 3: Write the implementation**

In `_snapshot_federation`, mirror what `_snapshot` already does:

```python
    from center_kb import assetstore, hashsync

    active_store = store if store is not None else assetstore.store_for_hub(handle)
    src_man = hashsync.build_manifest(fed_src, exclude=_FED_TOP_EXCLUDE)
    src_man, skipped = pubgate.split_allowlist(src_man)
    if active_store is not None:
        for entry_rel, entry_dir in federation.iter_entry_dirs(fed_src):
            for rel, sha in assetstore.synthesized_asset_entries(entry_dir).items():
                src_man[f"{entry_rel}/{rel}"] = sha
    dest_man = hashsync.build_manifest(dest, exclude=(assetstore.RECORD_NAME,))
    if active_store is not None:
        for entry_rel, entry_dir in federation.iter_entry_dirs(dest):
            for rel, sha in assetstore.synthesized_asset_entries(entry_dir).items():
                dest_man[f"{entry_rel}/{rel}"] = sha
```

and after `hashsync.apply_sync(fed_src, dest, changed, deleted)`, re-record on the destination side:

```python
    if active_store is not None:
        for _entry_rel, entry_dir in federation.iter_entry_dirs(dest):
            assetstore.divert_and_record(entry_dir, active_store)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_federation_nested.py tests/test_publish.py tests/test_assetcmd.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/publish.py tests/test_federation_nested.py
git commit -m "fix(publish): carry diverted assets through a hub-to-hub publish (F-D11)"
```

---

### Task 22: `scripts/gate.sh` runs what CI runs, on Windows too

Closes F-D14.

**Files:**
- Modify: `scripts/gate.sh`
- Modify: `scripts/check_package.py:105-113`
- Modify: `README.md:1006`
- Test: `tests/test_check_package.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `check_package.venv_bin(venv: Path) -> Path`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_check_package.py`:

```python
def test_venv_bin_picks_scripts_on_windows_layout(tmp_path):
    import sys

    sys.path.insert(0, "scripts")
    import check_package

    venv = tmp_path / "v"
    (venv / "Scripts").mkdir(parents=True)
    assert check_package.venv_bin(venv).name == "Scripts"


def test_venv_bin_picks_bin_on_posix_layout(tmp_path):
    import sys

    sys.path.insert(0, "scripts")
    import check_package

    venv = tmp_path / "v"
    (venv / "bin").mkdir(parents=True)
    assert check_package.venv_bin(venv).name == "bin"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_check_package.py -q -k venv_bin`
Expected: FAIL — `AttributeError: module 'check_package' has no attribute 'venv_bin'`

- [ ] **Step 3: Write the implementation**

In `scripts/check_package.py`, add and use:

```python
def venv_bin(venv: Path) -> Path:
    """A venv's executable directory: Scripts on Windows, bin elsewhere."""
    scripts = venv / "Scripts"
    return scripts if scripts.is_dir() else venv / "bin"
```

Replace `venv / "bin" / "kb"` in `installed_version` with `venv_bin(venv) / "kb"`.

Rewrite `scripts/gate.sh`. Change the header to describe what it actually is, add the `BIN` selection, T0 and the sdist smoke, and pass `--tag`:

```bash
#!/usr/bin/env bash
# Run the release gate on a dev machine, on ONE interpreter and ONE OS.
# CI (.github/workflows/_gate.yml) additionally runs the matrix:
# ubuntu x {3.11,3.12,3.13} plus windows-latest. Green here is necessary,
# not sufficient — it is what catches a red PR before you push, not a
# substitute for the matrix.
# Usage: scripts/gate.sh [--tag vX.Y.Z]
set -euo pipefail

TAG=""
if [ "${1:-}" = "--tag" ]; then TAG="${2:-}"; fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${TMPDIR:-/tmp}/kb-gate"
ARTIFACT="$WORK/artifact"
SDIST_VENV="$WORK/sdist"
RUNNER="$WORK/runner"

# A venv's executable directory: Scripts on Windows (Git Bash), bin elsewhere.
venv_bin() { if [ -d "$1/Scripts" ]; then echo "$1/Scripts"; else echo "$1/bin"; fi; }

if [ -x "$ROOT/.venv/bin/python" ]; then
    PY="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
    PY="$ROOT/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PY="$(command -v python)"
else
    echo "No Python interpreter found (tried .venv, python3, python)." >&2
    echo "  -> Run: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
    exit 1
fi
echo "==> Interpreter: $PY ($("$PY" --version 2>&1))"

cd "$ROOT"
rm -rf "$WORK" dist
mkdir -p "$WORK"

echo "==> T0: lint"
"$PY" -m ruff check .

echo "==> T1: unit/integration (source tree)"
"$PY" -m pytest -q

echo "==> Build wheel + sdist"
"$PY" -m build

echo "==> T2: packaging"
"$PY" -m venv "$ARTIFACT"
"$(venv_bin "$ARTIFACT")/pip" install --quiet dist/*.whl
if [ -n "$TAG" ]; then
    "$PY" scripts/check_package.py --venv "$ARTIFACT" --dist dist --tag "$TAG"
else
    "$PY" scripts/check_package.py --venv "$ARTIFACT" --dist dist
fi
"$PY" -m twine check --strict dist/*
uv lock --check

echo "==> T2b: sdist install smoke"
"$PY" -m venv "$SDIST_VENV"
"$(venv_bin "$SDIST_VENV")/pip" install --quiet dist/*.tar.gz
"$(venv_bin "$SDIST_VENV")/kb" --version
"$(venv_bin "$SDIST_VENV")/python" -c \
    "from importlib import resources; \
     print(len(resources.files('center_kb').joinpath('templates/init/config-hub.yaml').read_text()))"

echo "==> Build the runner venv"
"$PY" -m venv "$RUNNER"
"$(venv_bin "$RUNNER")/pip" install --quiet -r requirements-gate.txt

echo "==> T3: e2e on the artifact"
KB_VENV="$ARTIFACT" "$(venv_bin "$RUNNER")/pytest" tests-gate/e2e -q

echo "==> T4: regression"
KB_VENV="$ARTIFACT" "$(venv_bin "$RUNNER")/pytest" tests-gate/regression -q

echo ""
echo "Gate green on this interpreter/OS. CI still runs the matrix."
```

In `README.md:1018`, replace the line

```
It runs exactly what CI runs, in four tiers:
```

with

```
It runs the same tiers CI runs, on **one** interpreter and **one** OS — T0
lint, T1 tests, T2 packaging plus an sdist install smoke, T3 e2e and T4
regression against the built wheel. Green here is what catches a red PR
before you push; it is not the matrix. CI additionally runs ubuntu ×
3.11/3.12/3.13 plus windows-latest.
```

and renumber the tier list below it, which currently starts at T1, to start
at T0 (`ruff check .`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_check_package.py -q` and then `bash scripts/gate.sh` end to end (this is the slow one — expect 10–20 minutes).
Expected: PASS, and `gate.sh` reaches "Gate green".

- [ ] **Step 5: Commit**

```bash
git add scripts/gate.sh scripts/check_package.py README.md tests/test_check_package.py
git commit -m "fix(gate): add T0 lint and the sdist smoke, run on Windows, stop overclaiming (F-D14)"
```

---

### Task 23: `demo-federation.sh` runs on Windows

Closes the demo-script half of F-D9.

**Files:**
- Modify: `scripts/demo-federation.sh:7`
- Test: manual (the script is the test)

**Interfaces:**
- Consumes: nothing.
- Produces: a `DEMO_DIR` override.

- [ ] **Step 1: Reproduce the failure**

Run: `bash scripts/demo-federation.sh`
Expected on Windows: FAIL at step 3 with `could not reach hub '/tmp/tmp.XXXX/kb-hub'` — `mktemp -d` returns an MSYS path that native Python resolves to `C:\tmp\...`.

- [ ] **Step 2: Write the fix**

Replace `scripts/demo-federation.sh:7`:

```bash
# mktemp -d under Git Bash on Windows returns an MSYS path (/tmp/tmp.XXXX)
# that native Python resolves to C:\tmp\tmp.XXXX -- a directory the tool then
# cannot find. Default to a path both see the same way; override with DEMO_DIR.
if [ -z "${DEMO_DIR:-}" ]; then
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*) DEMO_DIR="$(mktemp -d "${LOCALAPPDATA:-$HOME}/kb-demo-XXXXXX")" ;;
        *) DEMO_DIR="$(mktemp -d)" ;;
    esac
fi
```

- [ ] **Step 3: Run the script to verify it passes**

Run: `bash scripts/demo-federation.sh`
Expected: all 12 steps complete, and the temp directory is removed by the existing `trap`.

- [ ] **Step 4: Verify it still passes on a POSIX path**

Run: `DEMO_DIR="$(mktemp -d)" bash scripts/demo-federation.sh`
Expected: all 12 steps complete.

- [ ] **Step 5: Commit**

```bash
git add scripts/demo-federation.sh
git commit -m "fix(demo): use a Windows-visible DEMO_DIR (F-D9)"
```

---

### Task 24: pin the scaffolded CI

Closes F-D13.

**Files:**
- Modify: `src/center_kb/initcmd.py:258-266` (`_render`)
- Modify: `src/center_kb/templates/init/kb-publish.yml`, `kb-code.yml`, `docker-compose-hub.yml`, `docker-compose-child.yml`
- Modify: `.github/workflows/kb-publish.yml`, `.github/workflows/release.yml`
- Test: `tests/test_init.py`, `tests/test_templates.py`

**Interfaces:**
- Consumes: `center_kb.__version__`.
- Produces: templates carry a `{version}` placeholder that `_render` fills.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_init.py`:

```python
def test_scaffolded_workflows_pin_the_scaffolding_version(tmp_path):
    from center_kb import __version__, initcmd

    dest = tmp_path / "child"
    dest.mkdir()
    initcmd.init_repo(dest, "child")
    wf = (dest / ".github" / "workflows" / "kb-publish.yml").read_text(encoding="utf-8")
    assert f"pip install center-kb=={__version__}" in wf
    assert "pip install center-kb\n" not in wf
    compose = (dest / "docker-compose.yml").read_text(encoding="utf-8")
    assert ":latest" not in compose
    assert f"center-kb:{__version__}" in compose


def test_no_template_leaves_an_unfilled_version_placeholder(tmp_path):
    from center_kb import initcmd

    for kind in ("hub", "child", "ba", "dev"):
        dest = tmp_path / kind
        dest.mkdir()
        initcmd.init_repo(dest, kind)
        for path in dest.rglob("*"):
            if path.is_file() and path.suffix in {".yml", ".yaml"}:
                assert "{version}" not in path.read_text(encoding="utf-8")
```

`template_map(kind)` covers all four kinds, so the placeholder scan is over every scaffold this release can produce.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_init.py -q -k "pin the scaffolding or placeholder"`
Expected: FAIL — the templates say `pip install center-kb` and `center-kb:latest`.

- [ ] **Step 3: Write the implementation**

In `src/center_kb/initcmd.py`:

```python
def _render(resource_name: str, text: str, repo_id: str) -> str:
    """Config templates carry {repo_id}; workflow and compose templates carry
    {version}, filled with the version of the CLI doing the scaffolding.

    An unpinned `pip install center-kb` inside a job that holds
    `id-token: write` means every child picks up whatever PyPI serves at run
    time, in a job able to write to the hub.
    """
    from center_kb import __version__

    if resource_name.startswith("config-"):
        return text.replace("{repo_id}", repo_id)
    return text.replace("{version}", __version__)
```

In `src/center_kb/templates/init/kb-publish.yml` and `kb-code.yml`, change every `pip install center-kb` to `pip install center-kb=={version}`, and SHA-pin the actions in the jobs holding `id-token: write`:

```yaml
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2
      - uses: actions/setup-python@42375524e23c412d93fb67b49958b491fce71c38  # v5.4.0
```

In `docker-compose-hub.yml` and `docker-compose-child.yml`, change `ghcr.io/vuonglq01685/center-kb:latest` to `ghcr.io/vuonglq01685/center-kb:{version}`.

In `.github/workflows/kb-publish.yml`, add a minimal permissions block and read the hub from the environment:

```yaml
jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
```

```yaml
      - name: Publish snapshot → PR on the hub
        run: kb publish --repo-id "${{ github.event.repository.name }}"
        env:
          CENTER_KB_HUB: ${{ secrets.KB_HUB_URL }}
          GH_TOKEN: ${{ secrets.GH_TOKEN }}
```

`--hub` already has `envvar="CENTER_KB_HUB"` (`cli.py:1464-1467`), so the URL never reaches argv.

In `.github/workflows/release.yml`, SHA-pin the actions used by the `pypi` job. `pypa/gh-action-pypi-publish@release/v1` is pinned to a *branch* today, which is a mutable ref in the job that holds `id-token: write` for Trusted Publishing. Resolve the release tag to its commit:

```bash
gh api repos/pypa/gh-action-pypi-publish/git/ref/tags/v1.12.4 --jq .object.sha
```

and write the result in, with the version as a trailing comment:

```yaml
      - uses: pypa/gh-action-pypi-publish@<sha from the command above>  # v1.12.4
```

Do the same for `actions/checkout` and `actions/download-artifact` in that job, using the SHAs above where they match. Jobs without `id-token: write` keep their major tags.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_init.py tests/test_templates.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/initcmd.py src/center_kb/templates/init/ .github/workflows/kb-publish.yml .github/workflows/release.yml tests/test_init.py tests/test_templates.py
git commit -m "fix(ci): pin center-kb and the id-token actions in scaffolded workflows (F-D13)"
```

---

### Task 25: docs, the scaffolded hub README, CHANGELOG, and the version bump

Closes F-D15 and F-D19, corrects the README lines this batch falsified, and ships 0.21.0.

**Files:**
- Modify: `src/center_kb/templates/init/federation-README.md`
- Modify: `tests/test_init.py:641` (the trip-wire)
- Modify: `README.md` (lines 479, 606, 846, and the T4 paragraph near 1026)
- Modify: `docs/deploy-remote-mcp.md:52`
- Modify: `CHANGELOG.md`, `pyproject.toml`
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: everything above.
- Produces: version `0.21.0`.

- [ ] **Step 1: Write the failing test**

Update the trip-wire in `tests/test_init.py` (currently at line 641) and add:

```python
def test_scaffolded_federation_readme_describes_the_full_mirror(tmp_path):
    from center_kb import initcmd

    dest = tmp_path / "hub"
    dest.mkdir()
    initcmd.init_repo(dest, "hub")
    text = (dest / "federation" / "README.md").read_text(encoding="utf-8")
    assert "L0" in text and "L3" in text
    assert "only holds the child's catalog and summaries" not in text
    assert "Content (L2/L3) stays in the child repo" not in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_init.py -q -k federation_readme`
Expected: FAIL — the scaffolded README still describes the pre-0.9 slim layout.

- [ ] **Step 3: Write the implementation**

Replace `src/center_kb/templates/init/federation-README.md`:

```markdown
# federation/

Full L0→L3 mirrors published by child repos, and the aggregate index built
from them.

Each child runs `kb publish --hub <this-repo-url-or-path>`, which writes
`federation/<repo-id>/` — the child's complete `.kb/` tree (index, manifests,
L2 summaries and L3 verbatim text), plus a hub-written `_meta.yaml` recording
the source repo and commit. `federation/index.yaml` is regenerated from those
snapshots on every publish.

**The hub is the only read source.** `kb query`, the MCP tools and the web UI
read from here, never from a child repo, so content becomes searchable when it
lands on this hub's default branch — and only then.

Two consequences worth knowing before you open this hub to more repos:

- Everything a child publishes is readable by everyone who can read this repo.
  Copyright and confidentiality are decided by who can clone the hub.
- `federation/registry.yaml` maps `owner/repo` → repo-id. Adding a mapping
  makes this hub *governed*: `kb publish` then refuses a repo-id the
  publisher's own remote is not registered for, and refuses direct pushes —
  contributions arrive by PR or through `kb ci-publish`. The registry is the
  review gate's roster; branch protection on this repo is what enforces it.
```

In `README.md` (the spec cites this reviewer's line numbers; these are the
current ones):

- **line 490**, in the `kb publish` bullet, replace

  ```
  on a local-path hub it commits directly (`--direct`); with neither flag it auto-picks direct for local-path hubs.
  ```

  with

  ```
  on a local-path hub it commits directly (`--direct`); with neither flag it picks direct only for a hub with no git remote, and for a remote hub it opens a PR — or refuses, naming both ways forward, when `gh` cannot open one.
  ```

- **line 617**, replace `and allowlisting this repo in the hub's
  `federation/registry.yaml` before publishing either document works.` with:

  ```
  and registering this repo in the hub's `federation/registry.yaml` before
  publishing either document works. A hub with a non-empty registry is
  *governed*: `kb publish` refuses a repo-id the publisher's own remote is
  not registered for, and refuses direct pushes outright.
  ```

- **line 857**, replace the `Allowlist the repo …` bullet with:

  ```
  - Register the repo in the hub's `federation/registry.yaml` (both `-code`
    and `-svc` publish through this). Note what the registry does and does
    not do: on the git path it is a *mistake guard* — a child's remote URL
    is self-asserted, so the check cannot authenticate anyone. What it
    enforces is the route: a governed hub takes PRs or `kb ci-publish`, and
    branch protection on the hub plus the OIDC intake are the actual
    security boundary.
  ```

- the T4 paragraph — append: *"T4's federation fixture is a flat v0.9.0 hub. A pre-0.9 federation in the `manifests/` slim layout is skipped by `federation.iter_entry_dirs` with a warning, so an un-republished pre-0.9 entry disappears from search after a hub upgrade — republish from the source repo to bring it back."*

In `docs/deploy-remote-mcp.md:52-53`, replace

```
   in `federation/registry.yaml` (a normal PR — also your review gate for who
   may contribute).
```

with

```
   in `federation/registry.yaml` (a normal PR). This is what the intake
   authorises against, and what makes the hub *governed* on the git path:
   `kb publish` then refuses an unregistered repo-id and refuses direct
   pushes. The registry cannot authenticate a git publisher — a remote URL
   is self-asserted — so branch protection on this repo is what makes the
   review route binding.
```

In `CHANGELOG.md`, add the 0.21.0 entry:

```markdown
## 0.21.0

### Breaking changes

- **A hub carrying a non-empty `federation/registry.yaml` is now governed.**
  `kb publish` refuses a `--repo-id` the publisher's own git remote is not
  registered for, and refuses direct pushes — a governed hub takes
  contributions by PR (`kb publish --pr`) or through `kb ci-publish`. Hubs
  with no registry are unaffected.
- **`kb publish` mirrors KB artefacts only** (`index.yaml`,
  `<doc>/_manifest.yaml`, `<doc>/*.md`, `<doc>/assets/*`). `.kb/config.yaml`,
  dotfiles and stray files are no longer published, and are **deleted from
  the hub** on the next publish. If a hub token was ever mirrored this way it
  is still in the hub's git history: **rotate it.** `kb doctor` names any
  entry that still holds such a file.
- **Auto mode no longer direct-pushes to a remote hub.** Previously it chose
  a PR only when the remote URL contained the substring `github`; every other
  remote hub got a silent push to its default branch. It now asks `gh`, and
  refuses with two named ways forward when a PR is impossible.
- **Repo-ids are rejected** when they collide case-insensitively with an
  existing entry, end in a dot, name a Win32 device (`CON`, `NUL`, `COM1`…)
  or exceed 64 characters.

### Fixed

- The intake writes each publish in its own `git worktree`; the serving clone
  never leaves the default branch, PRs are always based on it, and no publish
  reads another's branch (F-D3, F-D4).
- `kb reindex` commits `federation/index.yaml` only, and warns about other
  uncommitted content under `federation/` (F-D5).
- Hub credentials are no longer persisted in a clone's `.git/config` or passed
  on a git command line; the hub cache key is derived from the
  credential-free URL and the cache directory is `0700` (F-D7).
- A fresh hub clone sets `core.autocrlf=false` / `core.eol=lf`, so on Windows
  the next publish is no longer a whole-tree commit (F-D10).
- Asset bytes are hash-verified against their content-addressed name before
  being cached or served; `kb assets verify` hashes content; nested entries
  get their `_assets.yaml` at the leaf; a hub-to-hub publish carries diverted
  assets (F-D11).
- Uploads are capped before the body is buffered, and the intake rate limiter
  honours `X-Forwarded-For` only behind a declared trusted proxy
  (`CENTER_KB_TRUSTED_PROXIES`) (F-D12).
- OIDC `ref` claims are matched by exact segments; `federation/registry.yaml`
  accepts an optional `{repo_id, workflow}` mapping form that pins
  `job_workflow_ref` (F-D16).
- Drive-relative and backslash paths are refused in tar members and delete
  paths on every OS (F-D18).
- `kb publish`, `kb ci-publish` and `kb reindex` print one line instead of a
  traceback (F-D9).
- `scripts/gate.sh` runs T0 lint and an sdist smoke, passes `--tag`, and works
  on Windows; `scripts/demo-federation.sh` runs on Windows (F-D9, F-D14).
- Scaffolded workflows pin `center-kb==<version>` and SHA-pin the actions in
  jobs holding `id-token: write`; the scaffolded `federation/README.md`
  describes the current full-mirror architecture (F-D13, F-D15).
```

Bump `version = "0.21.0"` in `pyproject.toml`.

- [ ] **Step 4: Run the full suite**

Run: `.venv/Scripts/python -m pytest -q` then `.venv/Scripts/python -m ruff check .`
Expected: PASS, 0 failures, ruff clean. Expect 10–19 minutes.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/templates/init/federation-README.md README.md docs/deploy-remote-mcp.md CHANGELOG.md pyproject.toml tests/test_init.py
git commit -m "docs: describe the gate the code now enforces, ship 0.21.0 (F-D15, F-D19)"
```

---

## After the last task

1. Run `bash scripts/gate.sh` once, end to end, on Windows — Task 22 changed it, and it is the only place the Windows path selection is exercised.
2. Run `bash scripts/demo-federation.sh` once on Windows.
3. Write the review record for this batch under
   `docs/superpowers/reviews/`, matching what the B and C batches produced.
4. Open the PR with the spec and this plan linked, and the CHANGELOG's
   Breaking changes section quoted in the description.
