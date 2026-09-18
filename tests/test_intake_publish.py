from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path

import pytest

from center_kb import ghapp, intake


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.fixture
def hub(tmp_path):
    """Hub = local clone with a bare origin — like the server's hub cache."""
    bare = tmp_path / "hub-origin.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.email", "t@t")
    _git(seed, "config", "user.name", "t")
    (seed / ".kb").mkdir()
    (seed / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (seed / "federation").mkdir()
    (seed / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "init")
    _git(tmp_path, "clone", "--bare", str(seed), str(bare))
    clone = tmp_path / "hub-clone"
    _git(tmp_path, "clone", str(bare), str(clone))
    _git(clone, "config", "user.email", "srv@t")
    _git(clone, "config", "user.name", "srv")
    return clone


def _kb_archive() -> bytes:
    buf = io.BytesIO()
    files = {
        "index.yaml": b"docs:\n- id: doc-a\n  title: Doc A\n",
        "doc-a/_manifest.yaml": b"id: doc-a\ntitle: Doc A\nsections: []\n",
    }
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req):
        self.requests.append(req)
        status, body = self.responses.pop(0)
        return status, json.dumps(body).encode()


def _cfg(hub: Path, http) -> intake.IntakeConfig:
    return intake.IntakeConfig(
        hub_ref=str(hub),
        audience="https://kb.test",
        creds=ghapp.AppCreds(app_id="1", private_key_pem="unused-by-fake"),
        http=http,
        push_via_token_url=False,
    )


def test_intake_publish_creates_branch_and_pr(hub, monkeypatch):
    http = FakeHTTP(
        [
            (200, {"id": 9}),
            (201, {"token": "ghs_t"}),
            (201, {"html_url": "https://github.com/acme/hub/pull/7"}),
        ]
    )
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(
        intake.ghapp, "repo_full_from_url", lambda url: "acme/hub"
    )
    cfg = _cfg(hub, http)
    pr = intake.intake_publish(
        cfg, "flight-docs", "abc1234", "acme/flight-docs", [], _kb_archive()
    )
    assert pr.endswith("/pull/7")
    # branch publish/flight-docs exists on origin, contains snapshot + _meta + aggregate index
    _git(hub, "checkout", "publish/flight-docs")
    fed = hub / "federation" / "flight-docs"
    assert (fed / "index.yaml").exists()
    assert (fed / "_meta.yaml").exists()
    meta = (fed / "_meta.yaml").read_text(encoding="utf-8")
    assert "acme/flight-docs" in meta  # source_url from claims, not from payload
    assert (hub / "federation" / "index.yaml").exists()
    # back to main when done
    _git(hub, "checkout", "main")


def test_intake_publish_threads_the_hub_token_into_pull_and_push(tmp_path, monkeypatch):
    """Important 1 (mutants MU5/MU6): intake's freshest-main pull
    (gitio.pull(handle.root, token=handle.token), intake.py) and its
    push_via_token_url=False fallback push (gitio.push_branch(work, branch,
    handle.token)) both dropped handle.token with 87 tests still green --
    the gitio-level credential tests supply a token directly and cannot see
    either call site regress. This file's own `hub` fixture is a LOCAL path
    with .kb/, so resolve_hub never extracts a token there -- pre-seed a
    credentialed-hub-ref cache instead, the same trick
    test_publish.py's test_direct_publish_threads_the_hub_token_into_the_push
    uses for the one call site that IS already protected."""
    import hashlib
    import time

    from center_kb import gitio

    # Seed first, bare second (mirrors the fixture at the top of this file,
    # line 37): `clone --bare` from a seed that already has a commit on
    # "main" gives the bare repo's HEAD a symref that actually resolves.
    # Bare-first-then-push relies on the bare repo's own init.defaultBranch
    # matching the seed's "-b main" -- on a machine where that default is
    # "master" (or unset), the push lands on refs/heads/main while HEAD
    # still points at refs/heads/master, leaving every subsequent clone
    # with an unborn/ambiguous HEAD.
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.email", "t@t")
    _git(seed, "config", "user.name", "t")
    (seed / ".kb").mkdir()
    (seed / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (seed / "federation").mkdir()
    (seed / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "init")
    bare = tmp_path / "hub-origin.git"
    _git(tmp_path, "clone", "--bare", str(seed), str(bare))

    fake_hub_ref = "https://x-access-token:ghs_INTAKETOKEN@example.invalid/hub.git"
    stripped = "https://example.invalid/hub.git"
    cache_base = tmp_path / "cache"
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(cache_base))
    key = hashlib.sha1(stripped.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    cache = cache_base / key
    cache_base.mkdir(parents=True, exist_ok=True)
    _git(tmp_path, "clone", str(bare), str(cache))
    _git(cache, "config", "core.autocrlf", "false")  # a "healthy" cache
    _git(cache, "config", "user.name", "srv")
    _git(cache, "config", "user.email", "srv@t")
    (cache_base / f"{key}.last-pull").write_text(str(time.time()), encoding="utf-8")

    calls: list[dict] = []
    real_run = gitio.subprocess.run

    def spy(cmd, **kwargs):
        calls.append({"argv": list(cmd), "env": kwargs.get("env")})
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(gitio.subprocess, "run", spy)

    http = FakeHTTP(
        [
            (200, {"id": 9}),
            (201, {"token": "ghs_t"}),
            (201, {"html_url": "https://github.com/acme/hub/pull/7"}),
        ]
    )
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    cfg = intake.IntakeConfig(
        hub_ref=fake_hub_ref,
        audience="https://kb.test",
        creds=ghapp.AppCreds(app_id="1", private_key_pem="unused-by-fake"),
        http=http,
        push_via_token_url=False,
    )
    pr = intake.intake_publish(
        cfg, "flight-docs", "abc1234", "acme/flight-docs", [], _kb_archive()
    )
    assert pr.endswith("/pull/7")

    pull_calls = [
        c for c in calls
        if c["argv"][:2] == ["git", "pull"] and "--ff-only" in c["argv"]
    ]
    assert pull_calls, "intake_publish never pulled the freshest main"
    env = pull_calls[0]["env"]
    assert env is not None, "the pull carried no credential env at all"
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
    assert "ghs_INTAKETOKEN" not in pull_calls[0]["argv"]

    push_calls = [
        c for c in calls
        if c["argv"][:2] == ["git", "push"] and "publish/flight-docs" in c["argv"]
    ]
    assert push_calls, "intake_publish never pushed the fallback branch"
    env2 = push_calls[0]["env"]
    assert env2 is not None, "the fallback push carried no credential env at all"
    assert env2["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
    assert "ghs_INTAKETOKEN" not in push_calls[0]["argv"]


def test_intake_publish_nothing_changed_returns_empty(hub, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    http1 = FakeHTTP(
        [(200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"})]
    )
    intake.intake_publish(
        _cfg(hub, http1), "flight-docs", "abc1234", "acme/flight-docs", [], _kb_archive()
    )
    # 2nd run with identical content → no GitHub API calls, returns ""
    http2 = FakeHTTP([])
    pr = intake.intake_publish(
        _cfg(hub, http2), "flight-docs", "abc1234", "acme/flight-docs", [], _kb_archive()
    )
    assert pr == ""
    assert http2.requests == []


def test_intake_publish_applies_deletes(hub, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    responses = [
        (200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"}),
        (200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"}),
    ]
    http = FakeHTTP(responses)
    cfg = _cfg(hub, http)
    intake.intake_publish(
        cfg, "flight-docs", "aaa", "acme/flight-docs", [], _kb_archive()
    )
    # publish 2: delete doc-a/_manifest.yaml
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        content = b"docs: []\n"
        info = tarfile.TarInfo("index.yaml")
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    intake.intake_publish(
        cfg, "flight-docs", "bbb", "acme/flight-docs",
        ["doc-a/_manifest.yaml"], buf.getvalue(),
    )
    _git(hub, "checkout", "publish/flight-docs")
    assert not (hub / "federation" / "flight-docs" / "doc-a").exists()
    _git(hub, "checkout", "main")


def test_intake_publish_after_merge_resets_branch_from_main(hub, monkeypatch):
    """After the PR is merged, publishing again: the branch must reset from the new
    main (not reuse the old branch that diverged before the merge)."""
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    http = FakeHTTP(
        [
            (200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"}),
            (200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/2"}),
        ]
    )
    cfg = _cfg(hub, http)
    intake.intake_publish(
        cfg, "flight-docs", "aaa", "acme/flight-docs", [], _kb_archive()
    )
    # --no-ff: real merge commit (like GitHub's default merge) — fast-forward would
    # make the merge-base assert meaningless (old branch still an ancestor of main)
    _git(hub, "merge", "--no-ff", "--no-edit", "publish/flight-docs")
    # publish 2 with content changing 1 file
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        content = b"docs:\n- id: doc-a\n  title: Doc A v2\n"
        info = tarfile.TarInfo("index.yaml")
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    pr = intake.intake_publish(
        cfg, "flight-docs", "bbb", "acme/flight-docs", [], buf.getvalue()
    )
    assert pr.endswith("/pull/2")
    # the new branch must sit on the merged main, not the old history
    merge_base = _git(hub, "merge-base", "publish/flight-docs", "main").strip()
    main_sha = _git(hub, "rev-parse", "main").strip()
    assert merge_base == main_sha


def test_intake_publish_after_merge_identical_content_is_noop(hub, monkeypatch):
    """After the PR is merged, republishing identical content: the branch resets from
    a main that already has the content so porcelain is clean → returns "", no GitHub
    API calls."""
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    http1 = FakeHTTP(
        [(200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"})]
    )
    intake.intake_publish(
        _cfg(hub, http1), "flight-docs", "aaa", "acme/flight-docs", [], _kb_archive()
    )
    _git(hub, "merge", "--no-ff", "--no-edit", "publish/flight-docs")
    http2 = FakeHTTP([])
    pr = intake.intake_publish(
        _cfg(hub, http2), "flight-docs", "aaa", "acme/flight-docs", [], _kb_archive()
    )
    assert pr == ""
    assert http2.requests == []


def test_intake_publish_filters_non_allowlisted_files(hub, monkeypatch):
    """F-D9 finding 6: intake_publish's own allowlist call (intake.py's
    pubgate.split_allowlist, guarding uploads from the child's CI the same
    way F-D6 guards a direct `kb publish`) had no test coverage. A child's
    uploaded tar can hold a config.yaml (which may carry a hub token); it
    must never be written into the hub's federation/<rid>/ tree.

    Deliberately does not touch intake.py (owned by another agent in this
    same checkout right now) -- this only drives the already-shipped
    behavior through its public intake_publish() entry point."""
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    http = FakeHTTP(
        [(200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"})]
    )
    buf = io.BytesIO()
    files = {
        "index.yaml": b"docs:\n- id: doc-a\n  title: Doc A\n",
        "doc-a/_manifest.yaml": b"id: doc-a\ntitle: Doc A\nsections: []\n",
        "config.yaml": (
            b'hub: "https://x-access-token:ghs_SECRET@github.com/org/kb-hub.git"\n'
        ),
    }
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    cfg = _cfg(hub, http)
    pr = intake.intake_publish(
        cfg, "flight-docs", "abc1234", "acme/flight-docs", [], buf.getvalue()
    )
    assert pr.endswith("/pull/1")
    _git(hub, "checkout", "publish/flight-docs")
    fed = hub / "federation" / "flight-docs"
    assert (fed / "index.yaml").exists()
    assert not (fed / "config.yaml").exists()
    _git(hub, "checkout", "main")


def test_hub_manifest_excludes_meta(hub, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    http = FakeHTTP(
        [(200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"})]
    )
    intake.intake_publish(
        _cfg(hub, http), "flight-docs", "aaa", "acme/flight-docs", [], _kb_archive()
    )
    # the manifest is read from the main branch — not merged yet, so empty is correct;
    # reading the working tree after checking out the branch does show files.
    # hub_manifest reads the state of main (post-merge) — simulated by merging the
    # branch into main (--no-ff like GitHub's default merge):
    _git(hub, "merge", "--no-ff", "--no-edit", "publish/flight-docs")
    man = intake.hub_manifest(str(hub), "flight-docs")
    assert "index.yaml" in man
    assert "_meta.yaml" not in man


# ---- MEDIUM-1 (round 4, P45): the published-path bound must be true at
# ---- its own boundary -- a maximal compliant publish must clone rc=0
# ---- WITHOUT core.longpaths, at the client-prefix reserve this round
# ---- derives, not merely at a hand-picked short clone destination. -----


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="MAX_PATH / core.longpaths is a Windows-only concern; nothing "
    "to pin on a platform without either",
)
def test_maximal_compliant_publish_clones_without_longpaths(hub, monkeypatch):
    """Reproduces review-waveH-fix3-verdict.md's MEDIUM-1, at the fixed
    bound instead of the broken one: a repo-id at REPO_ID_MAX, a member
    path at exactly the NEW MAX_MEMBER_PATH_LEN, cloned into a
    destination at exactly the reserved CLIENT_PREFIX_RESERVE length --
    the published path lands at exactly SAFE_MAX_PATH characters end to
    end. Must clone rc=0 with `core.longpaths` explicitly OFF, not merely
    unset.

    Round 5 (M1/P59): round 4's claimed 214-character ceiling is WITHDRAWN
    -- it was a harness artifact (an `ignore_errors` rmtree could not
    delete git's read-only pack files, so every iteration after the first
    failed "destination path already exists", which reads exactly like a
    ceiling). Re-measured with a full integer sweep of the total absolute
    checkout path over [250, 266] at five clone-destination lengths (12,
    24, 48, 72, 100): ALL FIVE give 259 -> rc=0 and 260 -> rc=128, i.e.
    classic Windows MAX_PATH minus its terminating NUL, agreeing with the
    round-3 verdict. SAFE_MAX_PATH is now derived from 259 with a stated
    9-character margin; see intake.MAX_MEMBER_PATH_LEN's comment for the
    full term-by-term arithmetic and the round-5 report for the sweep log.

    Builds the clone destination under the real OS temp dir (not
    pytest's `tmp_path`, which is itself often already 80+ characters on
    Windows and would swallow the whole reserve before this test even
    starts) and skips -- rather than failing -- if this machine's own
    temp dir is already too deep to leave room for a controlled-length
    subdirectory: an environment-dependent path depth is not evidence
    against the bound.
    """
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    http = FakeHTTP(
        [(200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"})]
    )

    repo_id = "r" * intake.REPO_ID_MAX
    doc_prefix, doc_suffix = "doc1/", ".md"
    pad = intake.MAX_MEMBER_PATH_LEN - len(doc_prefix) - len(doc_suffix)
    member_name = doc_prefix + ("a" * pad) + doc_suffix
    assert len(member_name) == intake.MAX_MEMBER_PATH_LEN

    buf = io.BytesIO()
    files = {
        "index.yaml": b"docs:\n- id: doc-a\n  title: Doc A\n",
        "doc-a/_manifest.yaml": b"id: doc-a\ntitle: Doc A\nsections: []\n",
        member_name: b"x",
    }
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))

    pr = intake.intake_publish(
        _cfg(hub, http), repo_id, "abc1234", "acme/flight-docs", [], buf.getvalue()
    )
    assert pr.endswith("/pull/1")

    target_dest_len = intake.CLIENT_PREFIX_RESERVE - 1  # -1: the join separator
    # before "federation" is charged separately by the formula (see
    # CLIENT_PREFIX_RESERVE's own comment).
    temp_base = tempfile.gettempdir()
    unique = uuid.uuid4().hex[:8]
    if len(temp_base) + 1 + len(unique) > target_dest_len:
        pytest.skip(
            f"this machine's temp dir ({temp_base!r}, {len(temp_base)} chars) "
            f"leaves no room for a {target_dest_len}-char clone destination "
            "under the client-prefix reserve this bound assumes"
        )
    pad_len = target_dest_len - len(temp_base) - 1 - len(unique)
    clone_dest = Path(temp_base) / (("z" * pad_len) + unique)
    assert len(str(clone_dest)) == target_dest_len, str(clone_dest)

    published_path_len = (
        target_dest_len
        + 1  # separator between clone_dest and "federation"
        + len("federation/")
        + intake.REPO_ID_MAX
        + 1  # separator between repo-id and member
        + intake.MAX_MEMBER_PATH_LEN
    )
    assert published_path_len == intake.SAFE_MAX_PATH, published_path_len

    try:
        proc = subprocess.run(
            [
                "git",
                "-c",
                "core.longpaths=false",
                "clone",
                "--branch",
                f"publish/{repo_id}",
                "--single-branch",
                str(hub),
                str(clone_dest),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert proc.returncode == 0, (
            f"maximal compliant publish must clone rc=0 without "
            f"core.longpaths -- got rc={proc.returncode}\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr}"
        )
        checked_out = clone_dest / "federation" / repo_id / member_name
        assert checked_out.exists(), checked_out
        assert checked_out.read_bytes() == b"x"
    finally:
        shutil.rmtree(clone_dest, ignore_errors=True)


# ---- round 5 (M1/P45): the bound must admit the shape it most has to ------


def _asset_member(name: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name)
        info.size = 3
        info.mtime = 0
        tf.addfile(info, io.BytesIO(b"PNG"))
    return buf.getvalue()


_SHA256_HEX = "a" * 64


def test_content_addressed_assets_publish_on_the_default_store(tmp_path):
    """Regression: with the round-4 bound of 70, `kb ci-publish` could not
    upload ANY image on the DOCUMENTED DEFAULT configuration.

    `asset_store: mode: none` means `assets_will_divert` is False, so the
    diversion exemption at `_is_diverted_asset_name`'s call site does not
    apply and the full path-length bound runs. But a content-addressed
    basename is `<64-hex-sha256>.png` = 68 characters and ingestcmd always
    nests assets under `<doc-id>/assets/`, so the SHORTEST member path the
    product can produce is 77 -- already over 70. Measured against the
    pre-round-5 tree: 75, 76, 77, 85 and 95 all REFUSED 400 at
    divert=False, all ACCEPTED at divert=True; the whole archive aborted.

    The fix is the number, not the gate -- see MAX_MEMBER_PATH_LEN's
    comment. `assets_will_divert` stays the condition, because a
    non-diverted asset really is a tracked path a Windows client checks
    out, so the last case below must still be refused: this is a bound
    that now admits what it has to, not a bound that was removed.
    """
    shapes = {
        f"assets/{_SHA256_HEX}.png": 75,
        f"assets/{_SHA256_HEX}.webp": 76,
        f"d/assets/{_SHA256_HEX}.png": 77,
        f"arinc-424/assets/{_SHA256_HEX}.png": 85,
        f"boeing-737-800-fcom/assets/{_SHA256_HEX}.png": 95,
    }
    for i, (name, expected_len) in enumerate(shapes.items()):
        assert len(name) == expected_len, (name, len(name))
        dest = tmp_path / f"ok{i}"
        dest.mkdir()
        # assets_will_divert=False is the DEFAULT store, i.e. the exemption
        # is NOT in play -- this is the bound itself accepting the path.
        intake.safe_extract(_asset_member(name), dest, assets_will_divert=False)
        assert (dest / name).exists()

    # ...and the bound is still a bound: a doc-id long enough to push a
    # content-addressed asset past the budget is refused when it is not
    # diverted, and exempted when it is.
    over = "z" * 40 + f"/assets/{_SHA256_HEX}.png"
    assert len(over) > intake.MAX_MEMBER_PATH_LEN
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_asset_member(over), tmp_path / "no", assets_will_divert=False)
    assert exc.value.status == 400
    assert "core.longpaths" in exc.value.detail
    diverted = tmp_path / "yes"
    diverted.mkdir()
    intake.safe_extract(_asset_member(over), diverted, assets_will_divert=True)
    assert (diverted / over).exists()
