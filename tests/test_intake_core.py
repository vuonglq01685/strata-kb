from __future__ import annotations

import gzip
import io
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from strata_kb import assetstore, ghapp, gitio, intake, models

AUD = "https://kb.internal:8321"


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


def _token(pem, pub, **overrides):
    now = int(time.time())
    claims = {
        "iss": intake.GITHUB_ISSUER,
        "aud": AUD,
        "iat": now,
        "exp": now + 300,
        "repository": "acme/flight-docs",
        "ref": "refs/tags/kb-publish/20260715-010101",
    }
    claims.update(overrides)
    return pyjwt.encode(claims, pem, algorithm="RS256")


class TestVerifyOIDC:
    def test_valid_token_returns_claims(self, keypair):
        pem, pub = keypair
        claims = intake.verify_oidc(_token(pem, pub), AUD, key_resolver=lambda t: pub)
        assert claims["repository"] == "acme/flight-docs"

    @pytest.mark.parametrize(
        "override",
        [
            {"aud": "https://other"},
            {"iss": "https://evil.example"},
            {"exp": int(time.time()) - 10},
        ],
    )
    def test_bad_claims_rejected_401(self, keypair, override):
        pem, pub = keypair
        with pytest.raises(intake.IntakeError) as exc:
            intake.verify_oidc(
                _token(pem, pub, **override), AUD, key_resolver=lambda t: pub
            )
        assert exc.value.status == 401

    def test_wrong_signature_rejected(self, keypair):
        pem, _ = keypair
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with pytest.raises(intake.IntakeError) as exc:
            intake.verify_oidc(
                _token(pem, None), AUD, key_resolver=lambda t: other.public_key()
            )
        assert exc.value.status == 401


class TestAuthorize:
    REG = models.Registry(repos={"acme/flight-docs": "flight-docs"})

    def test_known_repo_returns_rid(self):
        claims = {
            "repository": "acme/flight-docs",
            "ref": "refs/tags/kb-publish/x",
        }
        assert intake.authorize(claims, self.REG) == "flight-docs"

    def test_unknown_repo_403_with_registry_hint(self):
        claims = {"repository": "evil/repo", "ref": "refs/tags/kb-publish/x"}
        with pytest.raises(intake.IntakeError) as exc:
            intake.authorize(claims, self.REG)
        assert exc.value.status == 403
        assert "registry.yaml" in exc.value.detail

    def test_non_publish_ref_403(self):
        claims = {"repository": "acme/flight-docs", "ref": "refs/heads/main"}
        with pytest.raises(intake.IntakeError) as exc:
            intake.authorize(claims, self.REG)
        assert exc.value.status == 403

    def test_registry_rid_with_path_separator_500(self):
        reg = models.Registry(repos={"acme/flight-docs": "../evil"})
        claims = {
            "repository": "acme/flight-docs",
            "ref": "refs/tags/kb-publish/x",
        }
        with pytest.raises(intake.IntakeError) as exc:
            intake.authorize(claims, reg)
        assert exc.value.status == 500


def _oidc_claims(**over):
    base = {
        "ref": "refs/tags/kb-publish/20260911-101500",
        "repository": "org/repo",
        "job_workflow_ref": "org/repo/.github/workflows/kb-publish.yml@refs/heads/main",
    }
    base.update(over)
    return base


PLAIN_REGISTRY = models.Registry(repos={"org/repo": "rid"})


def test_a_normal_tag_ref_is_accepted():
    assert intake.authorize(_oidc_claims(), PLAIN_REGISTRY) == "rid"


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
        intake.authorize(_oidc_claims(ref=ref), PLAIN_REGISTRY)
    assert exc.value.status == 403


PINNED_REGISTRY = models.Registry(
    repos={
        "org/repo": {
            "repo_id": "rid",
            "workflow": "org/repo/.github/workflows/kb-publish.yml@refs/heads/main",
        }
    }
)


def test_a_pinned_workflow_must_match():
    assert intake.authorize(_oidc_claims(), PINNED_REGISTRY) == "rid"


def test_a_different_workflow_is_refused_when_pinned():
    with pytest.raises(intake.IntakeError) as exc:
        intake.authorize(
            _oidc_claims(
                job_workflow_ref="org/repo/.github/workflows/evil.yml@refs/heads/main"
            ),
            PINNED_REGISTRY,
        )
    assert exc.value.status == 403


def _tar_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class TestSafeExtract:
    def test_extracts_regular_files(self, tmp_path):
        data = _tar_bytes({"index.yaml": b"docs: []", "d/s.md": b"hi"})
        intake.safe_extract(data, tmp_path)
        assert (tmp_path / "index.yaml").read_bytes() == b"docs: []"
        assert (tmp_path / "d" / "s.md").read_bytes() == b"hi"

    @pytest.mark.parametrize("name", ["../up.md", "/abs.md", "a/../../out.md"])
    def test_traversal_rejected_400(self, tmp_path, name):
        with pytest.raises(intake.IntakeError) as exc:
            intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)
        assert exc.value.status == 400

    def test_symlink_rejected_400(self, tmp_path):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo("link.md")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tf.addfile(info)
        with pytest.raises(intake.IntakeError) as exc:
            intake.safe_extract(buf.getvalue(), tmp_path)
        assert exc.value.status == 400

    def test_oversize_rejected_413(self, tmp_path):
        data = _tar_bytes({"big.md": b"x" * 2048})
        with pytest.raises(intake.IntakeError) as exc:
            intake.safe_extract(data, tmp_path, max_bytes=100)
        assert exc.value.status == 413


class TestStatusStore:
    def test_set_get_roundtrip_and_persistence(self, tmp_path):
        path = tmp_path / "status.json"
        store = intake.StatusStore(path)
        store.set("flight-docs", "abc1234", "done", pr_url="https://x/pull/1")
        got = store.get("flight-docs", "abc1234")
        assert got == {"state": "done", "pr_url": "https://x/pull/1", "detail": ""}
        # reload from file
        store2 = intake.StatusStore(path)
        assert store2.get("flight-docs", "abc1234")["state"] == "done"

    def test_unknown_returns_none(self, tmp_path):
        store = intake.StatusStore(None)
        assert store.get("x", "y") is None


def test_repo_lock_same_id_same_lock():
    assert intake.repo_lock("a") is intake.repo_lock("a")
    assert intake.repo_lock("a") is not intake.repo_lock("b")


# --- intake wiring: divert to the asset store, synthesized hub manifest ----


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.fixture
def hub_root(tmp_path):
    """Hub = local clone with an origin bare — mirrors the hub cache used by intake."""
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


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req):
        self.requests.append(req)
        status, body = self.responses.pop(0)
        return status, json.dumps(body).encode()


def _cfg(hub_root: Path, http) -> intake.IntakeConfig:
    return intake.IntakeConfig(
        hub_ref=str(hub_root),
        audience="https://kb.test",
        creds=ghapp.AppCreds(app_id="1", private_key_pem="unused-by-fake"),
        http=http,
        push_via_token_url=False,
    )


def _pr_http() -> FakeHTTP:
    """One successful publish's worth of GH App calls: installation lookup,
    token mint, PR create."""
    return FakeHTTP(
        [(200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"})]
    )


SHA_X = "e" * 64


def _archive_with_asset() -> bytes:
    return _tar_bytes(
        {
            "doc1/ch1-intro.md": b"text",
            f"doc1/assets/{SHA_X}.png": b"PNGBYTES",
        }
    )


def test_intake_diverts_assets_to_store(hub_root, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    cfg = _cfg(hub_root, _pr_http())
    store = assetstore.MemoryStore()
    intake.intake_publish(
        cfg, "child-a", "abc123", "org/child-a", [], _archive_with_asset(),
        store=store,
    )
    _git(hub_root, "checkout", "publish/child-a")
    dest = hub_root / "federation" / "child-a"
    assert store.get(f"{SHA_X}.png") == b"PNGBYTES"
    assert not (dest / "doc1" / "assets" / f"{SHA_X}.png").exists()
    assert (dest / "doc1" / "ch1-intro.md").exists()
    rec = models.load_yaml_model(dest / "_assets.yaml", models.AssetsRecord)
    assert rec.assets == [f"doc1/assets/{SHA_X}.png"]
    # the branch commit is text-only: no asset path is tracked
    tracked = gitio._run(hub_root, "ls-files", "--", "federation").stdout
    assert f"{SHA_X}.png" not in tracked
    _git(hub_root, "checkout", "main")


SHA_Y = "f" * 64


def _flaky_load_for(record_path: Path):
    """models.load_yaml_model replacement that raises PermissionError for
    exactly `record_path`'s entry, real for everything else.

    Matched on the trailing `federation/<rid>/<RECORD_NAME>` segments
    rather than the full path, because intake_publish reads the record
    from inside a freshly created temp worktree whose root is not known
    before the call -- but everything below `federation/` is identical
    there, so the suffix is enough to target one entry.

    Minor 6 (wave I-1 round 2 re-review): this used to match
    `path.name == RECORD_NAME`, i.e. EVERY `_assets.yaml` anywhere, while
    its signature promised targeting -- `record_path` was accepted and
    never read. There are no ruff `ARG` rules configured, so nothing in
    the tree would have caught it.
    """
    real_load = models.load_yaml_model
    target = record_path.parts[-3:]  # ("federation", "<rid>", "_assets.yaml")

    def _flaky(path, model):
        if path.parts[-3:] == target:
            raise PermissionError(f"permission denied: {path}")
        return real_load(path, model)

    return _flaky


def test_flaky_load_for_targets_only_the_entry_it_was_given(tmp_path):
    """Minor 6 (wave I-1 round 2 re-review): `_flaky_load_for` above takes
    a `record_path` and must actually use it. It used to match on
    `path.name == RECORD_NAME` -- every `_assets.yaml` anywhere, including
    a sibling entry's and the hub's own -- while its signature and
    docstring promised targeting; no ruff `ARG` rule is configured, so
    nothing in the tree would flag the unused argument. A non-target path
    must fall through to the real loader (FileNotFoundError here, since
    none of these files exist), never to the injected PermissionError."""
    flaky = _flaky_load_for(
        tmp_path / "federation" / "child-a" / assetstore.RECORD_NAME
    )

    # the target, reached through a DIFFERENT (worktree) root
    with pytest.raises(PermissionError):
        flaky(
            tmp_path / "wt-xyz" / "federation" / "child-a" / assetstore.RECORD_NAME,
            models.AssetsRecord,
        )

    for other in (
        tmp_path / "federation" / "child-b" / assetstore.RECORD_NAME,  # sibling entry
        tmp_path / assetstore.RECORD_NAME,  # the hub's own top-level record
        tmp_path / "federation" / "child-a" / "doc1" / assetstore.RECORD_NAME,
    ):
        with pytest.raises(FileNotFoundError):
            flaky(other, models.AssetsRecord)


def test_intake_second_publish_over_unreadable_record_aborts_without_deleting(
    hub_root, monkeypatch
):
    """P32, measured (this round's report): intake is explicitly
    incremental -- 'upload is incremental -- every file in the archive
    counts as changed' (intake.py's own comment) -- so a name diverted by
    an EARLIER publish survives only in the committed record;
    divert_and_record's merge exists precisely to fold that in. Before
    this fix, an unreadable committed record self-healed to empty inside
    that merge, degrading it to a plain overwrite -- with nothing new to
    divert this round, `merged == []` and the record was unlinked while
    the store still held the only copy of what it named. This must now
    abort with a terminal error instead, leaving the record byte-identical
    on the hub."""
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")

    # publish 1: a real asset, diverted and merged into main
    intake.intake_publish(
        _cfg(hub_root, _pr_http()), "child-a", "abc123", "org/child-a", [],
        _archive_with_asset(), store=assetstore.MemoryStore(),
    )
    _git(hub_root, "merge", "--no-ff", "--no-edit", "publish/child-a")
    record_path = hub_root / "federation" / "child-a" / assetstore.RECORD_NAME
    before = record_path.read_bytes()
    assert f"{SHA_X}.png".encode() in before  # sanity: a real, non-empty record
    # the merge itself can leave the clone's OWN checkout showing an
    # eol-only diff on an unrelated file (.kb/index.yaml) on this platform
    # -- not something this test is about, so pin it as a baseline rather
    # than asserting a pristine tree.
    status_before = gitio._run(hub_root, "status", "--porcelain").stdout

    monkeypatch.setattr(models, "load_yaml_model", _flaky_load_for(record_path))

    # publish 2: text-only upload -- nothing new to divert
    archive2 = _tar_bytes({"doc1/ch1-intro.md": b"text v2"})
    with pytest.raises(intake.IntakeError) as exc:
        intake.intake_publish(
            _cfg(hub_root, FakeHTTP([])), "child-a", "abc124", "org/child-a", [],
            archive2, store=assetstore.MemoryStore(),
        )
    assert exc.value.status == 500

    monkeypatch.undo()
    # bytes on the hub: untouched, not deleted or truncated
    assert record_path.exists()
    assert record_path.read_bytes() == before
    status_after = gitio._run(hub_root, "status", "--porcelain").stdout
    assert status_after == status_before  # the aborted attempt changed nothing


def test_intake_second_publish_new_asset_over_unreadable_record_does_not_truncate(
    hub_root, monkeypatch
):
    """Same shape as the test above, driving the other measured branch:
    'one new asset uploaded -> record replaced by that one asset, every
    earlier name dropped'. Before this fix, the self-healed-empty merge
    made divert_and_record write a record naming ONLY the new upload's
    asset, silently losing the first publish's name even though the store
    still held its bytes."""
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")

    intake.intake_publish(
        _cfg(hub_root, _pr_http()), "child-a", "abc123", "org/child-a", [],
        _archive_with_asset(), store=assetstore.MemoryStore(),
    )
    _git(hub_root, "merge", "--no-ff", "--no-edit", "publish/child-a")
    record_path = hub_root / "federation" / "child-a" / assetstore.RECORD_NAME
    before = record_path.read_bytes()
    status_before = gitio._run(hub_root, "status", "--porcelain").stdout

    monkeypatch.setattr(models, "load_yaml_model", _flaky_load_for(record_path))

    # publish 2: a brand-new second asset uploaded
    archive2 = _tar_bytes(
        {
            "doc2/ch2.md": b"text",
            f"doc2/assets/{SHA_Y}.png": b"OTHERBYTES",
        }
    )
    with pytest.raises(intake.IntakeError) as exc:
        intake.intake_publish(
            _cfg(hub_root, FakeHTTP([])), "child-a", "abc124", "org/child-a", [],
            archive2, store=assetstore.MemoryStore(),
        )
    assert exc.value.status == 500

    monkeypatch.undo()
    assert record_path.read_bytes() == before  # first name never dropped
    status_after = gitio._run(hub_root, "status", "--porcelain").stdout
    assert status_after == status_before  # the aborted attempt changed nothing


def test_intake_second_publish_over_zero_byte_record_aborts_without_deleting(
    hub_root, run_git, monkeypatch
):
    """Critical 1 (wave I-1 round 2, P47), driven through intake without
    faking the read: models.load_yaml_model is `yaml.safe_load(...) or
    {}`, so a zero-byte committed record reads back as a *successful*
    empty AssetsRecord -- the two tests above only ever exercise a read
    that RAISES. This exercises the shape shipped code produces on its
    own (models.save_yaml_model truncates before writing, no
    temp-file-and-rename), reaching the exact same pre-flight at
    intake.py's own `assetstore.load_record(dest)` call (unmodified this
    round -- the fix is entirely inside load_record).

    Important 1 (this batch's re-review): asserting only against
    hub_root's own checkout is not enough to see this. intake_publish
    writes into a throwaway worktree and commits onto branch
    publish/<rid> -- hub_root's checked-out tree is never touched either
    way, so bytes-on-hub_root and hub_root's porcelain pass identically
    whether or not the bug is present (kept below for completeness, not
    load-bearing on their own). The branch is what actually receives the
    commit that would delete the record, so that is what must be asserted
    to be able to see the deletion at all.

    Wave I-1 round 2 re-review (two nits, both fixed here): the branch
    assertion was not actually the tripwire -- under a mutation the run
    died first at `IndexError: pop from empty list` in `FakeHTTP.__call__`
    -- and the docstring was wrong about WHY the branch still resolves
    post-fix. Both are addressed inline below, where they are measured."""
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")

    # publish 1: a real asset, diverted and merged into main
    intake.intake_publish(
        _cfg(hub_root, _pr_http()), "child-a", "abc123", "org/child-a", [],
        _archive_with_asset(), store=assetstore.MemoryStore(),
    )
    _git(hub_root, "merge", "--no-ff", "--no-edit", "publish/child-a")
    record_path = hub_root / "federation" / "child-a" / assetstore.RECORD_NAME
    assert record_path.read_bytes()  # sanity: a real, non-empty committed record

    # simulate an interrupted publish's truncated write, committed to
    # main as-is -- shipped code, no mutation, no monkeypatch on the read.
    record_path.write_bytes(b"")
    run_git(hub_root, "add", "-A")
    run_git(hub_root, "commit", "-m", "simulate interrupted write")
    status_before = gitio._run(hub_root, "status", "--porcelain").stdout

    main_before = gitio._run(hub_root, "rev-parse", "HEAD").stdout.strip()

    # publish 2: text-only upload -- nothing new to divert.
    #
    # `_pr_http()` and not `FakeHTTP([])` (nit 1): with no responses
    # queued, a mutation that removes the pre-flight never reaches the
    # branch assertion below -- it dies at `IndexError: pop from empty
    # list` inside FakeHTTP.__call__ while minting an installation token,
    # so the assertion this test exists for does not run and the failure
    # names the fake HTTP client instead of the deletion. Pre-loaded
    # responses let a mutated run publish all the way through, which is
    # what makes the branch assertion the tripwire.
    http = _pr_http()
    archive2 = _tar_bytes({"doc1/ch1-intro.md": b"text v2"})
    aborted = None
    try:
        intake.intake_publish(
            _cfg(hub_root, http), "child-a", "abc124", "org/child-a", [],
            archive2, store=assetstore.MemoryStore(),
        )
    except intake.IntakeError as exc:
        aborted = exc

    # THE assertion, first and unconditional -- not inside a
    # pytest.raises(...) whose "DID NOT RAISE" would fire ahead of it. The
    # branch is what a real deletion lands on: pre-fix the commit removes
    # the record here and `git show` returns rc=128; post-fix it resolves.
    show = gitio._run(
        hub_root, "show", f"publish/child-a:federation/child-a/{assetstore.RECORD_NAME}"
    )
    assert show.returncode == 0, "the record was deleted on publish/child-a"
    assert show.stdout == ""  # zero bytes -- not further touched, not truncated

    # Why it resolves (nit 2 -- the docstring used to say "the pre-flight
    # aborts before _publish_in_worktree ever commits, so the record must
    # still resolve at this ref", which is right about the outcome and
    # wrong about the mechanism): intake RE-POINTS publish/<rid> at the
    # base branch's HEAD before doing any worktree work
    # (`worktree_add(..., reset=True)` whenever the entry is already on
    # main), so after an aborted run the branch IS main's HEAD, which
    # carries the record. Measured here rather than asserted in prose.
    branch_after = gitio._run(hub_root, "rev-parse", "publish/child-a").stdout.strip()
    assert branch_after == main_before

    # The mechanism that keeps the record alive: the pre-flight refuses
    # with a 500 before any commit -- and before any HTTP call, which is
    # what `FakeHTTP([])` used to assert by crashing.
    assert aborted is not None and aborted.status == 500
    assert http.requests == []

    # bytes on hub_root's own checkout, and its porcelain: unaffected
    # either way (Important 1) -- kept for completeness, not load-bearing.
    assert record_path.read_bytes() == b""
    status_after = gitio._run(hub_root, "status", "--porcelain").stdout
    assert status_after == status_before


def test_intake_upload_failure_aborts_before_commit(hub_root, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    cfg = _cfg(hub_root, FakeHTTP([]))  # no HTTP call should happen before the abort

    class _FailingStore(assetstore.MemoryStore):
        def put(self, name, data):
            raise assetstore.AssetStoreError("bucket down")

    before = gitio.head_commit(hub_root)
    with pytest.raises(intake.IntakeError) as exc:
        intake.intake_publish(
            cfg, "child-a", "abc123", "org/child-a", [], _archive_with_asset(),
            store=_FailingStore(),
        )
    assert exc.value.status == 502
    assert gitio.head_commit(hub_root) == before  # nothing committed


def test_intake_upload_failure_leaves_no_dirty_leftovers(hub_root, monkeypatch):
    """A failed divert must not leave uncommitted federation/ changes behind.

    Otherwise the next publish attempt for the same rid sees a dirty working
    tree: `dest.exists()` (a filesystem check) would be fooled into thinking
    the rid is already merged to main, and — worse — stray content from the
    aborted attempt could ride along uncommitted into a later, unrelated
    publish's commit.
    """
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")

    class _FailingStore(assetstore.MemoryStore):
        def put(self, name, data):
            raise assetstore.AssetStoreError("bucket down")

    archive1 = _tar_bytes(
        {
            "doc1/other.md": b"other",
            f"doc1/assets/{SHA_X}.png": b"PNGBYTES",
        }
    )
    with pytest.raises(intake.IntakeError):
        intake.intake_publish(
            _cfg(hub_root, FakeHTTP([])), "child-a", "abc123", "org/child-a",
            [], archive1, store=_FailingStore(),
        )
    status = gitio._run(
        hub_root, "status", "--porcelain", "--", "federation"
    ).stdout.strip()
    assert status == ""

    archive2 = _tar_bytes({"doc1/ch1-intro.md": b"text"})
    intake.intake_publish(
        _cfg(hub_root, _pr_http()), "child-a", "abc124", "org/child-a", [],
        archive2, store=assetstore.MemoryStore(),
    )
    _git(hub_root, "checkout", "publish/child-a")
    dest = hub_root / "federation" / "child-a"
    # not dragged along from the aborted attempt
    assert not (dest / "doc1" / "other.md").exists()
    assert (dest / "doc1" / "ch1-intro.md").exists()
    _git(hub_root, "checkout", "main")


def test_asset_shaped_name_without_a_configured_store_still_obeys_the_length_bound(
    hub_root, monkeypatch
):
    """The round-4 (P45) length-bound exemption for content-addressed asset
    paths (_is_diverted_asset_name's call site in safe_extract) is gated on
    diversion actually being active for THIS publish -- resolved once in
    intake_publish from the `store` test seam or else the hub's own
    asset_store config. hub_root has no asset_store block by default (spec
    A), and this call passes no store= override either, so an over-length,
    asset-shaped name stays a real tracked path here and must still be
    refused -- proving the exemption is not a blanket one.

    Builds its own archive rather than reusing _archive_with_asset(): that
    helper's 'doc1/assets/<sha256>.png' is 80 characters, which was over the
    old MAX_MEMBER_PATH_LEN of 70 but is legal under the 110 that Wave H
    round 5 re-derived from the measured 259/260 Windows ceiling. Reusing it
    would leave this test green while exercising nothing, which is exactly
    how this assertion decayed once already -- hence the explicit length
    assertion below, so the premise fails loudly if the bound moves again."""
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    cfg = _cfg(hub_root, _pr_http())
    over_length = ("z" * 40) + f"/assets/{SHA_X}.png"
    assert len(over_length) > intake.MAX_MEMBER_PATH_LEN, (
        f"this test needs an asset-shaped path OVER the bound; "
        f"{len(over_length)} is not over {intake.MAX_MEMBER_PATH_LEN}"
    )
    archive = _tar_bytes(
        {"doc1/ch1-intro.md": b"text", over_length: b"PNGBYTES"}
    )
    with pytest.raises(intake.IntakeError) as exc:
        intake.intake_publish(
            cfg, "child-a", "abc123", "org/child-a", [], archive,
        )
    assert exc.value.status == 400
    assert "UTF-16 code units" in str(exc.value)


def test_hub_manifest_synthesizes_assets_and_hides_record(hub_root, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    # hub_manifest() gates synthesis on the hub's own configured store (same
    # rule as publish._snapshot) -- the intake_publish call below bypasses
    # that via the store= test seam, but hub_manifest always reads
    # store_for_hub(handle), so the hub needs a real asset_store block for
    # the gated synthesis path to fire.
    (hub_root / ".kb" / "config.yaml").write_text(
        "asset_store:\n  mode: s3\n  bucket: kb-assets\n", encoding="utf-8"
    )
    intake.intake_publish(
        _cfg(hub_root, _pr_http()), "child-a", "abc123", "org/child-a", [],
        _archive_with_asset(), store=assetstore.MemoryStore(),
    )
    # hub_manifest reads main -- merge the publish branch in first
    _git(hub_root, "merge", "--no-ff", "--no-edit", "publish/child-a")
    man = intake.hub_manifest(str(hub_root), "child-a")
    assert man[f"doc1/assets/{SHA_X}.png"] == SHA_X
    assert "_assets.yaml" not in man
    assert "_meta.yaml" not in man


def test_intake_child_supplied_assets_record_is_ignored(hub_root, monkeypatch):
    """A malicious/stale tar can carry its own _assets.yaml at the rid root --
    it must never be synced verbatim into the hub-owned record. Only genuinely
    diverted assets (merged by divert_and_record) may end up in the record.
    """
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    bogus_record = models.AssetsRecord(assets=["doc1/assets/" + "e" * 64 + ".evil.png"])
    archive = _tar_bytes(
        {
            "doc1/ch1-intro.md": b"text",
            f"doc1/assets/{SHA_X}.png": b"PNGBYTES",
            assetstore.RECORD_NAME: (
                b"assets:\n- " + bogus_record.assets[0].encode() + b"\n"
            ),
        }
    )
    intake.intake_publish(
        _cfg(hub_root, _pr_http()), "child-a", "abc123", "org/child-a", [], archive,
        store=assetstore.MemoryStore(),
    )
    _git(hub_root, "checkout", "publish/child-a")
    dest = hub_root / "federation" / "child-a"
    rec = models.load_yaml_model(dest / assetstore.RECORD_NAME, models.AssetsRecord)
    assert bogus_record.assets[0] not in rec.assets
    assert rec.assets == [f"doc1/assets/{SHA_X}.png"]
    _git(hub_root, "checkout", "main")


@pytest.mark.parametrize(
    "name",
    [
        "C:evil.md", "C:/evil.md", "dir\\evil.md", "\\evil.md",
        # HIGH-1 / I-7: the position-0-anchored regex this replaced let all
        # of these through -- a drive letter, a reserved device name, or a
        # trailing dot/space in a NON-LEADING segment, each measured to
        # collapse (Windows) or commit verbatim and break every Windows
        # clone (Linux, where this service actually runs).
        "doc1/C:evil.md", "doc1/dir\\evil.md", "doc1/CON.md", "doc1/NUL.md",
        "doc1/COM1.md", "doc1/assets/NUL", "doc./a.md", "doc /a.md",
        "doc1/a.md.", "doc1/a.md ",
        # Round 2 / N-1: the round-1 list was built from the review's
        # examples rather than the rule -- these five shape families still
        # passed every guard and reproduced the identical measured outcome
        # (git clone rc=128, 0 files, every repo-id on the hub); see
        # test_shapes_this_round_newly_refuses_would_have_broken_every_
        # windows_clone below for the measured proof, not just the
        # refusal message.
        "doc1/NUL .txt", "doc1/NUL  .txt", "doc1/CON .md",  # device + trailing space before ext
        "doc1/CONIN$.md", "doc1/CONOUT$.md", "doc1/CONIN$",  # devices pubgate.WIN32_DEVICES lacked
        "doc1/a\x01b.md", "doc1/a\nb.md", "doc1/a\rb.md", "doc1/a\tb.md",
        "doc1/\x1b[31mred.md",  # C0 controls other than NUL
        "doc1/a<b.md", "doc1/a>b.md", "doc1/a\"b.md", "doc1/a|b.md",
        "doc1/a?b.md", "doc1/a*b.md",  # Windows-illegal, POSIX-legal
        # LOW-3 (round 3): the re-review's mutation pass found `cp < 0x20`
        # -> `cp < 0x1F` survives the whole suite -- U+001F is genuinely
        # clone-fatal (measured) and was simply never exercised at the
        # boundary.
        "doc1/a\x1fb.md",
        # LOW-6 (round 3): '.git' and its NTFS 8.3 short-name alias reach
        # the hub's own `git add` and fail there with a raw stderr 502
        # instead of a clean 400 -- a git rule, not a Windows one.
        "doc1/.git", "doc1/git~1",
    ],
)
def test_windows_path_shapes_in_a_tar_are_refused(name, tmp_path):
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes({name: b"x\n"}), tmp_path)
    assert exc.value.status == 400


def test_windows_path_shape_in_a_tar_does_not_collapse_into_dest(tmp_path):
    """I-7's exact measured bug: 'doc1/C:evil.md' used to be ACCEPTED and
    land at dest/evil.md (the 'doc1/' component silently dropped by
    pathlib's drive-shape parsing) -- refused now, so nothing is written."""
    with pytest.raises(intake.IntakeError):
        intake.safe_extract(_tar_bytes({"doc1/C:evil.md": b"x"}), tmp_path)
    assert list(tmp_path.iterdir()) == []


def _tree_sha_from_entries(repo: Path, entries: dict[str, bytes], index_file: Path) -> str:
    """A git tree object sha for exactly `entries` (path -> content), built
    with `update-index --index-info` + `write-tree` against a private
    GIT_INDEX_FILE -- plumbing, not `git add`/checkout, so no Windows
    working-tree path check runs while AUTHORING these names. That is the
    point: this reproduces the tree a Linux hub's real `git add` would
    produce verbatim (Linux git has no such check at all), so the clone
    below measures what a Windows CONSUMER does with it, not whether this
    machine can write the objects."""
    lines = []
    for path, content in entries.items():
        proc = subprocess.run(
            ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
            input=content, capture_output=True,
        )
        assert proc.returncode == 0, proc.stderr
        sha = proc.stdout.decode().strip()
        lines.append(f"100644 blob {sha}\t{path}\n".encode("utf-8"))
    env = {**os.environ, "GIT_INDEX_FILE": str(index_file)}
    proc = subprocess.run(
        ["git", "-C", str(repo), "update-index", "--add", "--index-info"],
        input=b"".join(lines), capture_output=True, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    proc = subprocess.run(
        ["git", "-C", str(repo), "write-tree"], capture_output=True, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.decode().strip()


@pytest.mark.skipif(
    sys.platform != "win32",
    reason=(
        "proves a Windows-client-specific outcome (git for Windows' "
        "is_valid_win32_path refusing the checkout) -- on Linux, git has "
        "no such check at all (is_valid_path() is a no-op macro there per "
        "the security review), so the identical tree clones cleanly; that "
        "asymmetry is the whole finding, not a platform gap in this test"
    ),
)
def test_shapes_this_round_newly_refuses_would_have_broken_every_windows_clone(tmp_path):
    """The standing instruction for this round: a test that only asserts
    the refusal message is not enough -- the outcome that matters is
    whether a Windows client can still clone the hub. This builds, with
    real git plumbing (never through safe_extract or any of this round's
    code), the exact tree a Linux hub's `git add` would produce for four
    of the shape families N-1 measured as still accepted before this
    round -- 'NUL .md' (a device name with the trailing space Windows
    strips before the extension), 'CONIN$.md' (a device name
    pubgate.WIN32_DEVICES did not carry), a C0 control other than NUL, and
    a Windows-illegal/POSIX-legal character -- alongside one ordinary
    control file, and shows a real `git clone` on this Windows machine
    fails completely: rc != 0, ZERO files checked out for the whole
    repository, control file included, not just the four poisoned
    entries. That is the measured outcome
    test_windows_path_shapes_in_a_tar_are_refused's new parametrizations
    (and _reject_path_shape's per-property predicate) now keep out of any
    archive the real intake path accepts."""
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)],
        check=True, capture_output=True,
    )
    # off for this authoring step only -- see the docstring above.
    subprocess.run(
        ["git", "-C", str(origin), "config", "core.protectNTFS", "false"],
        check=True, capture_output=True,
    )
    entries = {
        # LOW-7 (round 3): 'NUL .txt' is not a kb-artifact (.txt is not
        # kept by pubgate.is_kb_artifact) and would never reach a hub
        # through intake at all -- one quarter of this test's premise was
        # a path the allowlist already drops. 'NUL .md' makes all four
        # entries genuine kb-artifacts.
        "federation/alpha/doc1/NUL .md": b"x",
        "federation/alpha/doc1/CONIN$.md": b"x",
        "federation/alpha/doc1/a\x01b.md": b"x",
        "federation/alpha/doc1/a<b.md": b"x",
        "federation/alpha/ok.md": b"control",
    }
    tree_sha = _tree_sha_from_entries(origin, entries, tmp_path / "poison-index")
    commit = subprocess.run(
        ["git", "-C", str(origin), "commit-tree", tree_sha, "-m", "poison"],
        input=b"", capture_output=True,
    )
    assert commit.returncode == 0, commit.stderr
    commit_sha = commit.stdout.decode().strip()
    subprocess.run(
        ["git", "-C", str(origin), "update-ref", "refs/heads/main", commit_sha],
        check=True, capture_output=True,
    )
    clone_dir = tmp_path / "clone"
    proc = subprocess.run(
        ["git", "clone", str(origin), str(clone_dir)], capture_output=True, text=True,
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr
    checked_out_files = (
        [p for p in clone_dir.rglob("*") if p.is_file() and ".git" not in p.parts]
        if clone_dir.exists()
        else []
    )
    assert checked_out_files == []  # zero files -- including the control file


@pytest.mark.parametrize(
    "rel",
    [
        "C:boom", "dir\\boom.md", "C:/boom", "\\boom",
        "doc1/C:boom.md", "doc1/dir\\boom.md", "doc1/C:/boom",
        "CON.md", "NUL", "com1.txt", "doc1/Nul.md", "doc1/assets/lpt1",
        "boom.", "boom ", "doc1/boom. ", "boom..",
        "file.md:stream",  # LOW-4: an NTFS alternate data stream
        # Round 2 / N-1: enumerated by property, not by example (see the
        # ruling quoted in _reject_path_shape's docstring).
        "NUL .txt", "NUL  .txt", "CON .md",  # device name + trailing space before ext
        "CONIN$", "CONIN$.md", "CONOUT$.md",  # devices pubgate.WIN32_DEVICES lacked
        "COM0.md", "LPT0.md", "COM¹.md", "LPT².md",  # COM0/LPT0 + superscript aliases
        "a\x01b.md", "a\nb.md", "a\rb.md", "a\tb.md", "a\x1bb.md", "a\x7fb.md",
        "a<b.md", "a>b.md", 'a"b.md', "a|b.md", "a?b.md", "a*b.md",
        "a\x1fb.md",  # LOW-3: cp < 0x20 boundary, was untested exactly here
        ".git", "git~1", ".GIT", "GIT~1",  # LOW-6
    ],
)
def test_reject_path_shape_rejects_windows_shapes(rel):
    """Direct test of the interface Task 18 produces -- a pure string check,
    independent of pathlib's OS-dependent join/resolve/is_absolute behavior
    (a real trap here: on this Windows Python, `(dest / "C:boom").resolve()`
    lands safely under `dest` and hashsync._guard would NOT catch it either
    -- so an integration test alone, on this OS, cannot be trusted to prove
    this specific check is what's firing)."""
    with pytest.raises(intake.IntakeError) as exc:
        intake._reject_path_shape("some label", rel)
    assert exc.value.status == 400
    assert rel in exc.value.detail


@pytest.mark.parametrize(
    "rel", ["boom", "dir/boom.md", "a/b/c.md", "./leading-dot.md", "../up.md", "a/../b.md"]
)
def test_reject_path_shape_accepts_shapes_it_does_not_own(rel):
    """'.'/'..'/empty components are a traversal question, not a
    cross-platform-shape one -- _reject_traversal owns refusing them (see
    below); _reject_path_shape must not refuse a delete path's legitimate
    leading './x' spelling."""
    intake._reject_path_shape("some label", rel)  # must not raise


@pytest.mark.parametrize(
    "rel", ["../up.md", "/abs.md", "a/../../out.md", "", ".", "./.", "a/./.."]
)
def test_reject_traversal_rejects_escapes_and_degenerate_names(rel):
    with pytest.raises(intake.IntakeError) as exc:
        intake._reject_traversal("some label", rel)
    assert exc.value.status == 400


@pytest.mark.parametrize("rel", ["boom", "dir/boom.md", "./leading.md", "a/./b.md"])
def test_reject_traversal_accepts_normal_and_dot_prefixed_shapes(rel):
    parts = intake._reject_traversal("some label", rel)
    assert parts  # non-empty, no '.' components survive
    assert all(p not in ("", ".", "..") for p in parts)


@pytest.mark.parametrize("rel", ["boom", "dir/boom.md", "a/b/c.md"])
def test_reject_path_shape_accepts_posix_shapes(rel):
    intake._reject_path_shape("some label", rel)  # must not raise


@pytest.mark.parametrize("rel", ["C:boom", "dir\\boom.md"])
def test_windows_path_shapes_in_deletes_are_refused(rel, intake_cfg, make_upload):
    # A real, valid archive -- not b"" -- so that without the fix, the call
    # would actually reach the hub and complete successfully (a spurious
    # tarfile.TarError on an empty/invalid archive would 400 regardless of
    # whether the path-shape check ran, making the assertion meaningless).
    with pytest.raises(intake.IntakeError) as exc:
        intake.intake_publish(
            intake_cfg, "alpha", "c1", "org/alpha", [rel], make_upload("alpha")
        )
    assert exc.value.status == 400


def test_intake_deletes_cannot_touch_assets_record(hub_root, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    intake.intake_publish(
        _cfg(hub_root, _pr_http()), "child-a", "abc124", "org/child-a",
        ["_assets.yaml"], _archive_with_asset(), store=assetstore.MemoryStore(),
    )
    _git(hub_root, "checkout", "publish/child-a")
    assert (hub_root / "federation" / "child-a" / "_assets.yaml").exists()
    _git(hub_root, "checkout", "main")


# ---- HIGH-2: member-count cap ------------------------------------------


def test_max_tar_members_is_in_a_sane_band():
    """N-7: every cap test monkeypatches MAX_TAR_MEMBERS, so a mutant
    changing its shipped VALUE (e.g. to 100_000_000, which would let the
    original ~11.1M-member zero-byte-member bomb back in under the 50 MiB
    byte budget) survived the whole suite. The exact figure is a design
    choice (see the constant's own comment); this only holds the order of
    magnitude the design reasoning argues for."""
    assert 100 <= intake.MAX_TAR_MEMBERS <= 100_000


def test_max_member_name_is_in_a_sane_band():
    """Same shape as the MAX_TAR_MEMBERS check above, for the round-2
    HIGH-2 name-length bound: it must be generous enough for any real
    repo-relative path and nowhere near large enough to make the
    per-character scans it bounds expensive."""
    assert 255 <= intake.MAX_MEMBER_NAME <= 65_536


def test_member_count_cap_rejected_413(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "MAX_TAR_MEMBERS", 3)
    members = {f"doc1/f{i}.md": b"" for i in range(4)}
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes(members), tmp_path)
    assert exc.value.status == 413
    assert "3" in exc.value.detail


def test_member_count_within_cap_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "MAX_TAR_MEMBERS", 3)
    members = {f"doc1/f{i}.md": b"x" for i in range(3)}
    intake.safe_extract(_tar_bytes(members), tmp_path)  # must not raise
    assert len(list((tmp_path / "doc1").iterdir())) == 3


def test_zero_byte_members_still_count_against_the_byte_budget(tmp_path):
    """HIGH-2: the content-byte cap used to count only declared *content*
    (member.size), which stays 0 for an all-zero-byte-member archive no
    matter how many members it holds -- headers are not free."""
    members = {f"doc1/f{i}.md": b"" for i in range(50)}
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes(members), tmp_path, max_bytes=50 * 400)
    assert exc.value.status == 413


# ---- HIGH-2 round 2: pax/GNU long-name header amplification -------------


def _pax_upload(name: str, content: bytes = b"") -> bytes:
    """A tar.gz whose one member's name is carried in a pax 'path='
    extended header rather than the ustar name field -- the shape that let
    a 97 KB gzip upload declare an arbitrarily long member name (measured:
    100 MB), which is what made the pre-round-2 per-character scans and
    the flat-512-byte header charge exploitable in the first place."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT) as tf:
        info = tarfile.TarInfo("placeholder.md")
        info.pax_headers = {"path": name}
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def test_oversized_member_name_is_refused_before_any_per_character_scan(
    tmp_path, monkeypatch
):
    """Ruling: 'refuse over it before any per-character scanning runs'.
    Proven directly, not inferred from timing -- patch both per-character
    scans (_reject_path_shape, and _reject_display_spoofing, the one the
    round-2 re-review measured at 5.35s of the 6.57s total for a 100 MB
    pax name) to blow up if called at all, and show an oversized name is
    still refused: the length check alone stops it, before either scan
    ever runs."""

    def _boom(*_a, **_k):
        raise AssertionError("a per-character scan ran on an oversized name")

    monkeypatch.setattr(intake, "_reject_path_shape", _boom)
    monkeypatch.setattr(intake, "_reject_display_spoofing", _boom)
    data = _pax_upload("a" * (intake.MAX_MEMBER_NAME + 1))
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(data, tmp_path)
    assert exc.value.status == 400
    assert str(intake.MAX_MEMBER_NAME) in exc.value.detail


def test_member_name_length_bound_is_off_by_one_correct(tmp_path, monkeypatch):
    """The bound must refuse a name one character OVER the limit and
    accept one exactly AT it. Proven against a small patched value so the
    accepted case is a real, writable path -- an actual
    MAX_MEMBER_NAME-length (4096) single path component runs into this
    host filesystem's OWN component-length limit, a different, unrelated
    concern (N-3, not in this round's scope) and not what this test is
    about."""
    monkeypatch.setattr(intake, "MAX_MEMBER_NAME", 20)
    ok_name = "doc1/" + "a" * 15  # 20 characters exactly
    assert len(ok_name) == 20
    intake.safe_extract(_tar_bytes({ok_name: b"x"}), tmp_path)  # must not raise
    assert (tmp_path / "doc1" / ("a" * 15)).exists()

    over_dir = tmp_path / "over"
    over_dir.mkdir()
    over_name = ok_name + "a"  # 21 characters
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes({over_name: b"x"}), over_dir)
    assert exc.value.status == 400
    assert "20" in exc.value.detail


def test_pax_long_name_header_is_charged_its_real_size_not_a_flat_block(tmp_path):
    """HIGH-2 round 2: a pax 'path=' header's own bytes used to be charged
    a flat tarfile.BLOCKSIZE (512) no matter how large the header actually
    was. A name within MAX_MEMBER_NAME (so the length bound alone cannot
    explain a refusal) but long enough to need ~4 KiB of real header space
    (measured: offset_data - offset == 4096 for this exact name) -- with
    max_bytes between the old flat charge (512) and the real one (~4096),
    the byte-budget check alone must be what fires (413): with the flat
    charge, total stays at 512 (<= max_bytes) and the budget never trips,
    so this must reach the fixed code's real-size charge to 413 at all."""
    data = _pax_upload("a" * 3000)
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(data, tmp_path, max_bytes=2000)
    assert exc.value.status == 413


# ---- MEDIUM-1: the deletes hub-owned-file filter ------------------------


@pytest.mark.parametrize(
    "bypass", ["./_assets.yaml", ".//_assets.yaml", "_ASSETS.yaml", "_Assets.YAML"]
)
def test_intake_deletes_hub_owned_bypass_spellings_are_ignored(
    bypass, hub_root, monkeypatch
):
    """MEDIUM-1: the pre-fix filter compared the raw string for EXACT
    equality against '_assets.yaml', so a leading './', a doubled slash, or
    a case difference all bypassed it -- but the bypass only bites a file
    that already exists (hashsync.apply_sync's delete loop is `if
    target.exists(): unlink`, a no-op on a first publish where the record
    is created afterward by divert_and_record, not synced in by
    apply_sync). Matches the security review's own repro shape: publish A
    creates the record, publish B carries the crafted delete."""
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    intake.intake_publish(
        _cfg(hub_root, _pr_http()), "child-a", "abc123", "org/child-a",
        [], _archive_with_asset(), store=assetstore.MemoryStore(),
    )
    intake.intake_publish(
        _cfg(hub_root, _pr_http()), "child-a", "abc124", "org/child-a",
        [bypass], _tar_bytes({"doc1/other.md": b"other"}),
        store=assetstore.MemoryStore(),
    )
    _git(hub_root, "checkout", "publish/child-a")
    assert (hub_root / "federation" / "child-a" / "_assets.yaml").exists()
    _git(hub_root, "checkout", "main")


@pytest.mark.parametrize("bypass", ["_assets.yaml ", "_assets.yaml."])
def test_intake_deletes_hub_owned_trailing_shapes_are_refused(bypass, intake_cfg, make_upload):
    """A trailing space/dot also folds onto '_assets.yaml' on a
    Windows/macOS filesystem -- closed here as a hard refusal (via
    _reject_path_shape's trailing-dot/space rule) rather than a silent
    drop, which is at least as safe: the whole publish is refused, so
    nothing is deleted either way."""
    with pytest.raises(intake.IntakeError) as exc:
        intake.intake_publish(
            intake_cfg, "alpha", "c1", "org/alpha", [bypass], make_upload("alpha")
        )
    assert exc.value.status == 400


def test_clean_deletes_normalizes_a_kept_path_before_returning_it():
    """MEDIUM-1's second half: the normalized spelling, not the raw
    attacker string, must be what flows downstream (so divert_and_record
    subtracts the same string apply_sync actually deletes)."""
    assert intake._clean_deletes(["./doc1/keep.md"]) == ["doc1/keep.md"]
    assert intake._clean_deletes(["_assets.yaml"]) == []


def test_clean_deletes_only_drops_hub_owned_names_at_the_rid_root(tmp_path):
    """N-10: hub-owned bookkeeping (_assets.yaml, _meta.yaml) is written
    ONLY at the rid root (assetstore.py: `dest / RECORD_NAME`; intake.py:
    `dest / "_meta.yaml"`), never nested -- so matching on the basename
    regardless of depth silently dropped a child's own, legitimately
    nested 'doc1/_assets.yaml' delete too. The root spelling (in every
    normalized form) must still be dropped; a nested file with the same
    name must survive."""
    assert intake._clean_deletes(["_assets.yaml"]) == []
    assert intake._clean_deletes(["./_assets.yaml"]) == []
    assert intake._clean_deletes(["_ASSETS.yaml"]) == []
    assert intake._clean_deletes(["_meta.yaml"]) == []
    assert intake._clean_deletes(["doc1/_assets.yaml"]) == ["doc1/_assets.yaml"]
    assert intake._clean_deletes(["doc1/_meta.yaml"]) == ["doc1/_meta.yaml"]
    assert intake._clean_deletes(["a/b/_assets.yaml"]) == ["a/b/_assets.yaml"]


# ---- MEDIUM-2: degenerate member shapes must 400, never 500 -------------


@pytest.mark.parametrize("name", ["doc1/C:", "."])
def test_degenerate_member_names_refused_by_validation_not_by_a_crash(name, tmp_path):
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)
    assert exc.value.status == 400


@pytest.mark.parametrize("order", [("assets", "assets/x.png"), ("assets/x.png", "assets")])
def test_a_file_and_directory_name_collision_in_the_tar_is_refused_not_500(order, tmp_path):
    """MEDIUM-2: a member named 'assets' (a file) and a member
    'assets/x.png' collide on disk regardless of shape/traversal
    validation -- extraction itself raises OSError (PermissionError /
    FileExistsError / NotADirectoryError depending on OS and order), which
    must be translated into a clean 400, not an uncaught 500 that leaves
    the job's status stuck at "processing" forever."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name in order:
            content = b"" if name == "assets" else b"PNGBYTES"
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(buf.getvalue(), tmp_path)
    assert exc.value.status == 400


def test_pax_header_nul_in_path_is_refused_not_500(tmp_path):
    """A NUL byte cannot live in a ustar/GNU name field (it is
    NUL-terminated), but a pax extended header's 'path' key carries one
    through fine, and tarfile hands it to `member.name` verbatim."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT) as tf:
        info = tarfile.TarInfo("placeholder.md")
        info.size = 1
        info.pax_headers = {"path": "ev\x00il.md"}
        tf.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(buf.getvalue(), tmp_path)
    assert exc.value.status == 400


# ---- LOW-2: attacker-controlled names must not reach a raw log line -----


def test_escape_for_log_neutralizes_control_characters_and_caps_length():
    assert "\n" not in intake._escape_for_log("evil\nFAKE LOG LINE: admin logged in")
    assert "\r" not in intake._escape_for_log("evil\rcarriage")
    long_name = "x" * 500
    escaped = intake._escape_for_log(long_name, limit=50)
    assert len(escaped) <= len("...(truncated)") + 50


def test_skipped_file_names_reach_the_log_escaped(hub_root, monkeypatch, caplog):
    """A newline is not even a legal character in a Windows filename (the
    OS itself refuses to create one), so this cannot be proven by actually
    extracting a hostile name on this test OS -- it drives the real log
    call site (`_publish_in_worktree`'s "not KB artefacts" warning) with a
    hostile name coming out of `pubgate.split_allowlist`'s return value
    instead, independent of what safe_extract could or could not write."""
    from strata_kb import pubgate

    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    dangerous = "evil\nFAKE: admin logged in.txt"
    monkeypatch.setattr(
        pubgate, "split_allowlist", lambda manifest, **kw: ({}, [dangerous])
    )
    with caplog.at_level("WARNING", logger="strata_kb.intake"):
        intake.intake_publish(
            _cfg(hub_root, _pr_http()), "child-a", "abc123", "org/child-a", [],
            _archive_with_asset(), store=assetstore.MemoryStore(),
        )
    warnings = "\n".join(r.message for r in caplog.records)
    assert "\nFAKE" not in warnings
    assert "\\nFAKE" in warnings


# ---- LOW-3: the case-collision rule must run on the real intake path ----


def test_dest_for_rid_rejects_a_case_colliding_sibling(tmp_path):
    federation_dir = tmp_path / "federation"
    (federation_dir / "Victim").mkdir(parents=True)
    with pytest.raises(intake.IntakeError) as exc:
        intake._dest_for_rid(federation_dir, "victim")
    assert exc.value.status == 400
    assert "Victim" in exc.value.detail or "collide" in exc.value.detail.lower()


def test_dest_for_rid_still_accepts_a_normal_repeat_publish(tmp_path):
    """The rid's OWN existing directory must not collide with itself."""
    federation_dir = tmp_path / "federation"
    (federation_dir / "alpha").mkdir(parents=True)
    intake._dest_for_rid(federation_dir, "alpha")  # must not raise


# ---- LOW-5: Unicode normalization for collision detection only ---------


def test_nfc_and_nfd_forms_of_the_same_member_name_collide(tmp_path):
    import unicodedata

    nfc_name = f"doc1/{unicodedata.normalize('NFC', 'café')}.md"
    nfd_name = f"doc1/{unicodedata.normalize('NFD', 'café')}.md"
    assert nfc_name != nfd_name  # different bytes, same rendered glyphs
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name in (nfc_name, nfd_name):
            info = tarfile.TarInfo(name)
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(buf.getvalue(), tmp_path)
    assert exc.value.status == 400


def test_nfd_only_names_are_not_refused_outright(tmp_path):
    """A macOS client legitimately produces NFD -- refusing it outright
    would reject real content; only a same-archive NFC collision is a
    refusal."""
    import unicodedata

    nfd_name = f"doc1/{unicodedata.normalize('NFD', 'café')}.md"
    intake.safe_extract(_tar_bytes({nfd_name: b"x"}), tmp_path)  # must not raise
    written = list((tmp_path / "doc1").iterdir())
    assert len(written) == 1
    assert written[0].name == unicodedata.normalize("NFD", "café") + ".md"  # exact spelling kept


@pytest.mark.parametrize(
    "name",
    [
        "doc1/\u202eevil.md",  # RTL override
        "doc1/\u200bevil.md",  # zero-width space
        "doc1/\ufeffevil.md",  # BOM / zero-width no-break space
    ],
)
def test_bidi_and_formatting_control_characters_are_refused(name, tmp_path):
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)
    assert exc.value.status == 400


def test_lone_surrogate_in_a_member_name_is_refused(tmp_path):
    name = "doc1/\udcffevil.md"
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)
    assert exc.value.status == 400


def test_resolve_hub_or_503_converts_a_locked_cache_into_a_503_not_a_500(
    tmp_path, monkeypatch, run_git, undiscardable_hub_cache
):
    """Important 3: hub.resolve_hub can now raise gitio.GitError when a
    legacy cache's discard hits a locked file (the common Windows cause:
    another process still has .kb-work/search.sqlite3 open). Before this
    fix, _resolve_hub_or_503's only guard was `if handle is None` -- a
    raised exception turned a recoverable cache problem into an unhandled
    500 instead of the degraded 503 this path exists to give.

    Ruling P49 (round 5): the undiscardable-cache recipe is now the shared
    `undiscardable_hub_cache` fixture, which has a real POSIX mechanism, so
    the round-4 `skipif(sys.platform != "win32")` is gone and this runs on
    the three ubuntu legs of _gate.yml T1 as well. See tests/conftest.py."""
    from strata_kb import hub as hub_mod

    bare = tmp_path / "hub.git"
    run_git(tmp_path, "init", "--bare", str(bare))
    seed = tmp_path / "seed"
    seed.mkdir()
    run_git(seed, "init", "-b", "main")
    run_git(seed, "config", "user.email", "t@t")
    run_git(seed, "config", "user.name", "t")
    (seed / ".kb").mkdir()
    (seed / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "init")
    run_git(seed, "remote", "add", "origin", str(bare))
    run_git(seed, "push", "-u", "origin", "HEAD")

    cache_base = tmp_path / "cache"
    monkeypatch.setenv("STRATA_KB_HUB_CACHE", str(cache_base))
    key = hub_mod.cache_key(str(bare))
    legacy = cache_base / key
    run_git(tmp_path, "clone", str(bare), str(legacy))
    run_git(legacy, "config", "core.autocrlf", "true")  # legacy -- needs re-clone

    with undiscardable_hub_cache(legacy):
        with pytest.raises(intake.IntakeError) as exc:
            intake._resolve_hub_or_503(str(bare))
        assert exc.value.status == 503


# ==========================================================================
# Round 3 (wave-h-fix-round-3): HIGH-1 (pax global headers / memory bound),
# N-4 correction (Bidi_Control / Default_Ignorable, ZWNJ/ZWJ allowance),
# N-3 (path length), MEDIUM-2 (repo-id/member drift), MEDIUM-3 (directory
# count), N-5's missing test, and the round-2 re-review's LOWs.
# ==========================================================================


# ---- HIGH-1: _BoundedTarStream bounds the read/seek call itself, before -
# ---- tarfile can act on it -- unit-level, isolated from tarfile entirely -


class TestBoundedTarStream:
    def test_read_over_budget_raises_before_touching_the_inner_stream(self):
        """The allocation this exists to prevent is the inner .read() call
        itself -- proven by showing it never happens: the inner stream's
        position is still 0 after the raise."""
        inner = io.BytesIO(b"x" * 10_000)
        stream = intake._BoundedTarStream(inner, limit=100)
        with pytest.raises(intake.IntakeError) as exc:
            stream.read(10_000)
        assert exc.value.status == 413
        assert inner.tell() == 0

    def test_read_within_budget_passes_through_then_refuses(self):
        inner = io.BytesIO(b"x" * 10_000)
        stream = intake._BoundedTarStream(inner, limit=100)
        assert stream.read(60) == b"x" * 60
        assert stream.read(40) == b"x" * 40
        with pytest.raises(intake.IntakeError) as exc:
            stream.read(1)
        assert exc.value.status == 413

    def test_seek_forward_past_budget_raises_before_the_seek(self):
        inner = io.BytesIO(b"x" * 10_000)
        stream = intake._BoundedTarStream(inner, limit=100)
        with pytest.raises(intake.IntakeError) as exc:
            stream.seek(5000)
        assert exc.value.status == 413
        assert inner.tell() == 0

    def test_seek_within_budget_charges_the_forward_span(self):
        inner = io.BytesIO(b"x" * 10_000)
        stream = intake._BoundedTarStream(inner, limit=100)
        stream.seek(80)  # charges 80 (0 -> 80); within budget, does not raise
        assert inner.tell() == 80
        stream.seek(90)  # charges 10 more (80 -> 90) = 90 total; still fine
        assert inner.tell() == 90
        with pytest.raises(intake.IntakeError) as exc:
            stream.seek(101)  # would charge 11 more = 101 total; over budget
        assert exc.value.status == 413

    def test_unbounded_read_request_is_refused(self):
        inner = io.BytesIO(b"x" * 10)
        stream = intake._BoundedTarStream(inner, limit=100)
        with pytest.raises(intake.IntakeError) as exc:
            stream.read(-1)
        assert exc.value.status == 413

    def test_non_absolute_seek_is_refused(self):
        inner = io.BytesIO(b"x" * 10)
        stream = intake._BoundedTarStream(inner, limit=100)
        with pytest.raises(intake.IntakeError):
            stream.seek(1, 1)  # whence=SEEK_CUR -- tarfile never uses this


# ---- HIGH-1: end-to-end -- a pax GLOBAL ('g') header charged correctly --


def _pax_global_upload(comment_size: int) -> bytes:
    """A tar.gz whose GLOBAL ('g') pax header carries `comment_size` bytes
    of real header content, followed by one ordinary member -- the exact
    shape HIGH-1 (round 3) measured as charged a flat 512 regardless of
    real size (CPython's _proc_pax patches `next.offset` only for
    XHDTYPE/SOLARIS_XHDTYPE, never XGLTYPE)."""
    raw = io.BytesIO()
    raw.write(tarfile.TarInfo.create_pax_global_header({"comment": "b" * comment_size}))
    info = tarfile.TarInfo("doc1/ok.md")
    info.size = 0
    raw.write(info.tobuf(tarfile.PAX_FORMAT, "utf-8", "surrogateescape"))
    raw.write(b"\0" * 1024)
    return gzip.compress(raw.getvalue(), 9)


def test_pax_global_header_is_charged_its_real_size_not_a_flat_block(tmp_path):
    """HIGH-1: with max_bytes between the old flat charge (512) and the
    header's real size (well over 3000), the byte-budget/stream-bound
    check alone must be what fires -- exactly the round-2 proof pattern
    (test_pax_long_name_header_is_charged_its_real_size_not_a_flat_block),
    now for the header type round 2 left uncharged."""
    data = _pax_global_upload(3000)
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(data, tmp_path, max_bytes=2000)
    assert exc.value.status == 413


def test_pax_global_header_within_budget_is_accepted(tmp_path):
    data = _pax_global_upload(100)
    intake.safe_extract(data, tmp_path)  # must not raise
    assert (tmp_path / "doc1" / "ok.md").exists()


# ---- LOW-5: chained extended headers hit RecursionError, not a 500 ------


def test_pathologically_chained_extended_headers_are_refused_not_500(tmp_path):
    """CPython's tar header parser recurses once per chained pax/GNU-
    longname header (_proc_pax/_proc_gnulong each fetch the NEXT header via
    a recursive call). Enough chaining hits RecursionError, which is
    neither OSError, ValueError nor tarfile.TarError -- unhandled, it used
    to escape safe_extract entirely and reach the route's generic 500
    backstop on a surface whose whole point is that attacker-chosen input
    gets a 400."""
    raw = io.BytesIO()
    for _ in range(2000):
        raw.write(tarfile.TarInfo.create_pax_global_header({"c": "x"}))
    info = tarfile.TarInfo("doc1/ok.md")
    info.size = 0
    raw.write(info.tobuf(tarfile.PAX_FORMAT, "utf-8", "surrogateescape"))
    raw.write(b"\0" * 1024)
    data = gzip.compress(raw.getvalue())
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(data, tmp_path)
    assert exc.value.status == 400


def test_chained_extended_headers_on_a_later_member_are_refused_not_500(tmp_path):
    """round-4 LOW (M18): the test above puts its 2,000 chained pax GLOBAL
    headers BEFORE the archive's only real member -- tarfile.open() itself
    reads the first header eagerly (see _BoundedTarStream's HIGH-1
    docstring), so that reproduction actually exercises safe_extract's
    OTHER except RecursionError (wrapping tarfile.open() itself, a few
    lines above the member loop), not the one wrapping the `for member in
    tf` loop body. Proven reachable but never pinned: a first, ordinary
    member is yielded and PROCESSED (written to disk) by one loop
    iteration, successfully returning control to the loop -- only the
    SECOND call to tf.next() (fetching what would become the second
    member) recurses. Asserts the first member's write survived (proof
    the loop body ran at least once, i.e. this really is the mid-iteration
    arm) alongside the clean 400."""
    raw = io.BytesIO()
    first = tarfile.TarInfo("doc1/ok.md")
    body = b"first member content"
    first.size = len(body)
    raw.write(first.tobuf(tarfile.GNU_FORMAT, "utf-8", "surrogateescape"))
    raw.write(body)
    pad = (-len(body)) % tarfile.BLOCKSIZE
    raw.write(b"\0" * pad)
    for _ in range(2000):
        raw.write(tarfile.TarInfo.create_pax_global_header({"c": "x"}))
    second = tarfile.TarInfo("doc1/never-reached.md")
    second.size = 0
    raw.write(second.tobuf(tarfile.PAX_FORMAT, "utf-8", "surrogateescape"))
    raw.write(b"\0" * 1024)
    data = gzip.compress(raw.getvalue())
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(data, tmp_path)
    assert exc.value.status == 400
    assert "pathologically nested" in exc.value.detail
    assert (tmp_path / "doc1" / "ok.md").read_bytes() == body
    assert not (tmp_path / "doc1" / "never-reached.md").exists()


def _sparse_member_archive(realsize: int, physical_bytes: int) -> bytes:
    """A GNU sparse member (pax version 0.1: a pax extended header
    carrying GNU.sparse.map + GNU.sparse.realsize, immediately preceding
    an ordinary regular-type member) whose REAL/expanded size
    (`realsize`) is far larger than the bytes actually stored in the
    archive (`physical_bytes`, split into two equal-sized data segments
    at offset 0 and offset realsize-half so the sparse map has a real
    gap). This is the exact shape CPython's tarfile applies
    `_apply_pax_info`'s `next.size = int(value)` override for -- the
    member's `.size` as seen by the safe_extract loop becomes `realsize`
    even though only `physical_bytes` were ever written to the stream."""
    half = physical_bytes // 2
    gap_offset = realsize - half
    pax = tarfile.TarInfo._create_pax_generic_header(
        {
            "GNU.sparse.map": f"0,{half},{gap_offset},{half}",
            "GNU.sparse.realsize": str(realsize),
        },
        tarfile.XHDTYPE,
        "utf-8",
    )
    member = tarfile.TarInfo("doc1/sparse.bin")
    member.size = physical_bytes
    header = member.tobuf(tarfile.GNU_FORMAT, "utf-8", "surrogateescape")
    body = b"\1" * physical_bytes
    pad = (-physical_bytes) % tarfile.BLOCKSIZE
    raw = pax + header + body + b"\0" * pad
    return gzip.compress(raw)


def test_sparse_member_is_charged_by_its_expanded_size_not_its_wire_size(tmp_path):
    """round-4 LOW (M20): the per-member `total` charge
    (`member.size + (member.offset_data - member.offset)`) is commented
    as catching a GNU sparse member's EXPANDED size even though
    _BoundedTarStream's own byte-read budget cannot see it (sparse holes
    are synthesized zero-fill, never actually read from the stream) --
    unproven before this test. A 40-byte-on-the-wire sparse member
    declaring a 10,000,020-byte real size must be REFUSED at
    max_bytes=1,000,000 purely from that declared size -- proof the
    charge uses `member.size` (post pax-override, the realsize) and not
    the tiny number of bytes actually read off the gzip stream, which
    stays far under max_bytes regardless (isolating this from
    _BoundedTarStream's own, separate byte-budget check)."""
    data = _sparse_member_archive(realsize=10_000_020, physical_bytes=40)
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(data, tmp_path, max_bytes=1_000_000)
    assert exc.value.status == 413
    assert "exceeds 1000000 bytes" in exc.value.detail


def test_sparse_member_control_same_wire_size_small_realsize_is_accepted(tmp_path):
    """No-op control for the test above: identical wire bytes (40 physical
    bytes, same pax-sparse shape), but a realsize that ALSO fits under
    max_bytes -- must be accepted. Proves the refusal above is driven
    specifically by the declared realsize crossing the budget, not by
    some unrelated property of a pax-sparse-shaped archive (e.g. the pax
    header itself, or the GNU sparse type) being refused outright."""
    data = _sparse_member_archive(realsize=100, physical_bytes=40)
    intake.safe_extract(data, tmp_path, max_bytes=1_000_000)  # must not raise
    assert (tmp_path / "doc1" / "sparse.bin").exists()


# ---- N-3: published path length -----------------------------------------


def test_max_member_path_len_is_in_a_sane_band():
    # round-4 (P45): the bound now reserves CLIENT_PREFIX_RESERVE chars for
    # the client's own clone-root prefix out of a measured SAFE_MAX_PATH
    # ceiling, so the member-path share shrank from the old ~184 to ~70.
    # Lower bound guards against a regression back toward "no reserve was
    # actually taken"; upper bound guards against a regression back above
    # the measured Windows ceiling.
    assert 40 <= intake.MAX_MEMBER_PATH_LEN <= 120
    assert intake.MAX_MEMBER_PATH_LEN < intake.MAX_MEMBER_NAME


def test_a_path_within_max_member_name_but_over_the_publish_length_is_refused(
    tmp_path,
):
    """N-3: MAX_MEMBER_NAME (4096) does not bound this -- a member path
    well under it can still break every Windows clone without
    core.longpaths, so the message must name both the limit and the
    workaround."""
    name = "doc1/" + "a" * (intake.MAX_MEMBER_PATH_LEN + 1) + ".md"
    assert len(name) < intake.MAX_MEMBER_NAME
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)
    assert exc.value.status == 400
    assert "core.longpaths" in exc.value.detail
    assert str(intake.MAX_MEMBER_PATH_LEN) in exc.value.detail


def test_path_length_bound_is_off_by_one_correct(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "MAX_MEMBER_PATH_LEN", 20)
    ok_name = "d/" + "a" * 18  # 20 characters exactly
    assert len(ok_name) == 20
    intake.safe_extract(_tar_bytes({ok_name: b"x"}), tmp_path)  # must not raise

    over_dir = tmp_path / "over"
    over_dir.mkdir()
    over_name = ok_name + "a"  # 21 characters
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes({over_name: b"x"}), over_dir)
    assert exc.value.status == 400


# ---- MEDIUM-2: repo-id and member-name device rules share one set -------


def test_win32_devices_is_shared_not_duplicated():
    """MEDIUM-2: the member-name check (_reject_path_shape) and
    pubgate.normalize_repo_id must read the exact same object, or the
    drift this round closes (normalize_repo_id accepted 'LPT0' while the
    member rule refused it -- and a registry entry mapping a publisher to
    that repo-id broke every Windows clone of the whole hub) can reopen the
    moment one of them grows a local copy again.

    Round 4 (P30): intake.py no longer imports WIN32_DEVICES itself --
    both call sites now go through pubgate.is_reserved_device_name, the
    one shared predicate (stem-extraction + trailing-space-strip +
    case-fold + membership, not just the set). Checking THAT function
    object's identity is the stronger version of this pin: it catches a
    future drift in the CHECK logic (e.g. one call site regaining its own
    inline rstrip/upper), not just in the underlying set."""
    from strata_kb import pubgate

    assert intake.is_reserved_device_name is pubgate.is_reserved_device_name


def test_dest_for_rid_refuses_a_windows_device_repo_id(tmp_path):
    federation_dir = tmp_path / "federation"
    with pytest.raises(intake.IntakeError) as exc:
        intake._dest_for_rid(federation_dir, "LPT0")
    assert exc.value.status == 400


# ---- MEDIUM-3: directory count -------------------------------------------


def test_max_tar_directories_is_in_a_sane_band():
    assert 100 <= intake.MAX_TAR_DIRECTORIES <= 100_000


def test_directory_count_cap_rejected_413(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "MAX_TAR_DIRECTORIES", 3)
    members = {f"d{i}/x.md": b"" for i in range(4)}  # 4 distinct directories
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes(members), tmp_path)
    assert exc.value.status == 413
    assert "3" in exc.value.detail


def test_directory_count_within_cap_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "MAX_TAR_DIRECTORIES", 3)
    members = {f"d{i}/x.md": b"" for i in range(3)}
    intake.safe_extract(_tar_bytes(members), tmp_path)  # must not raise
    assert len(list(tmp_path.iterdir())) == 3


def test_directory_count_charges_shared_prefixes_once(tmp_path, monkeypatch):
    """Members sharing a directory prefix must not double-charge it --
    only DISTINCT directory paths count, matching the real inode cost."""
    monkeypatch.setattr(intake, "MAX_TAR_DIRECTORIES", 1)
    members = {"d/a.md": b"", "d/b.md": b"", "d/c.md": b""}  # one directory: 'd'
    intake.safe_extract(_tar_bytes(members), tmp_path)  # must not raise
    assert len(list((tmp_path / "d").iterdir())) == 3


# ---- N-5: the round-2 fix finally gets a regression test -----------------


def test_resolve_raising_is_translated_into_a_clean_400(tmp_path, monkeypatch):
    """N-5 (round 2), test written per the round-3 re-review: resolve()
    itself can raise, and the one statement between the validators and the
    write's try used to sit OUTSIDE the translated region. Proven directly
    -- monkeypatch resolve() to raise for this one member -- rather than
    hunting for a real input that fails naturally on this platform, the
    same technique this round's ordering test already uses."""
    import pathlib

    real_resolve = pathlib.Path.resolve

    def fake_resolve(self, *a, **k):
        if "boomname" in str(self):
            raise OSError(22, "simulated: resolve() failed on this path")
        return real_resolve(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "resolve", fake_resolve)
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes({"doc1/boomname.md": b"x"}), tmp_path)
    assert exc.value.status == 400


# ---- N-4 correction: Bidi_Control / Default_Ignorable, ZWNJ/ZWJ allowed -


def test_arabic_letter_mark_is_refused(tmp_path):
    """N-4 correction (i): U+061C ARABIC LETTER MARK is Bidi_Control=Yes
    but was missing from the ruling's hand-written list of bidi
    characters -- a mutant reverting the named-property check back to that
    list would miss exactly this character and this test."""
    name = "doc1/؜evil.md"
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)
    assert exc.value.status == 400


@pytest.mark.parametrize(
    "name",
    [
        "doc1/​evil.md",  # ZWSP
        "doc1/﻿evil.md",  # BOM / ZWNBSP
        "doc1/a­b.md",  # SOFT HYPHEN
        "doc1/a᠎b.md",  # MONGOLIAN VOWEL SEPARATOR
    ],
)
def test_invisible_characters_already_refused_before_this_round_still_are(
    name, tmp_path
):
    """N-4 correction (ii): none of these alter visual ORDER, so a
    predicate that only refused Bidi_Control characters would silently
    drop all four and reopen LOW-5's invisible-name spoof. The predicate
    needs the separate Default_Ignorable clause too."""
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)
    assert exc.value.status == 400


def test_combining_grapheme_joiner_is_refused(tmp_path):
    """CGJ (U+034F) is Default_Ignorable and category Mn (not Cf) --
    accepted before round 3's blanket-Cf check, closed by the
    named-property predicate. P44 (round 4): applying the "does this
    select how a real character displays, or is it purely an
    order/collation control" test, CGJ stays refused -- its only job is
    to change canonical-reordering/collation behaviour, it never selects
    a glyph for a preceding character, and it is never itself part of
    what a name says."""
    name = "doc1/a͏b.md"
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)
    assert exc.value.status == 400


def test_variation_selector_is_now_allowed_and_round_trips(tmp_path):
    """MEDIUM-3 (round 3 re-review): VS16 (U+FE0F) is Default_Ignorable
    and category Mn, so round 3's literal "invisible minus {ZWJ, ZWNJ}"
    predicate refused it -- '❤️.md' (HEAVY BLACK HEART + VS16) went from
    accepted (pre-round-3) to refused (round 3), a real regression the
    re-review caught. P44 (round 4): a variation selector chooses which
    glyph the PRECEDING real character renders as -- an emoji
    PRESENTATION sequence is how that name is spelled, exactly as ZWNJ is
    in Persian -- so it is ruled back in, and the collision key (which
    already strips every Default_Ignorable code point, VS16 included)
    is what keeps allowing it safe rather than the refusal."""
    name = "doc1/a️b.md"
    intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)  # must not raise
    assert (tmp_path / "doc1" / "a️b.md").read_bytes() == b"x"


def test_heart_emoji_name_is_accepted_and_round_trips(tmp_path):
    """The exact MEDIUM-3 repro: a real emoji presentation sequence, not
    a synthetic VS16-after-ASCII probe."""
    name = "doc1/❤️.md"  # HEAVY BLACK HEART + VS16 == the "❤️" glyph
    intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)  # must not raise
    assert (tmp_path / "doc1" / "❤️.md").read_bytes() == b"x"


def test_mongolian_free_variation_selector_is_allowed_and_round_trips(tmp_path):
    """P44 (round 4): Mongolian FVS1-4 (U+180B-180D, U+180F) select which
    written form of the PRECEDING Mongolian letter is meant -- the same
    glyph-variant-selection job a variation selector does, for a script
    whose letterforms are genuinely ambiguous in plain text without it,
    so it is ruled in by the identical reasoning."""
    name = "doc1/ᠠ᠋.md"  # MONGOLIAN LETTER A + FVS1
    intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)  # must not raise
    assert (tmp_path / "doc1" / "ᠠ᠋.md").read_bytes() == b"x"


def test_mongolian_vowel_separator_stays_refused(tmp_path):
    """U+180E is a DIFFERENT character from the FVS set (a word-internal
    spacing control, not a glyph-variant selector) and is deliberately
    NOT part of the P44 (round 4) allowlist -- a pre-existing refusal
    (already pinned by test_invisible_characters_already_refused_before_
    this_round_still_are), repeated here so the FVS carve-out above
    cannot be silently widened to swallow it too."""
    name = "doc1/a᠎b.md"
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)
    assert exc.value.status == 400


@pytest.mark.parametrize(
    "name",
    [
        "doc1/aᅟb.md",  # HANGUL CHOSEONG FILLER
        "doc1/aᅠb.md",  # HANGUL JUNGSEONG FILLER
        "doc1/aㅤb.md",  # HANGUL FILLER
        "doc1/aﾠb.md",  # HALFWIDTH HANGUL FILLER
    ],
)
def test_hangul_fillers_stay_refused(name, tmp_path):
    """P44 (round 4): a Hangul filler renders as blank width -- a
    placeholder for an ABSENT jamo in an otherwise-incomplete syllable
    block, not a rendering of any real one. A name built from fillers
    alone spells nothing, so refusing them loses no real writing system
    the way refusing ZWNJ would; it is the same all-invisible-name risk
    LOW-5 exists to close."""
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)
    assert exc.value.status == 400


@pytest.mark.parametrize(
    "name",
    [
        "doc1/a឴b.md",  # KHMER VOWEL INHERENT AQ
        "doc1/a឵b.md",  # KHMER VOWEL INHERENT AA
    ],
)
def test_khmer_inherent_vowels_stay_refused(name, tmp_path):
    """P44 (round 4): ordinary Khmer orthography never writes these --
    the inherent vowel is implicit -- so they exist for internal/
    technical representation, not for spelling a name a person would
    actually choose; refusing them loses nothing real."""
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)
    assert exc.value.status == 400


def test_soft_hyphen_is_refused_decision():
    """Decision (round 3, genuinely ambiguous per the ruling, decided
    here): U+00AD SOFT HYPHEN is refused. It is invisible and
    Default_Ignorable exactly like ZWNJ/ZWJ, but unlike them it only ever
    marks an OPTIONAL hyphenation point -- no filesystem path needs a
    discretionary hyphen the way Persian/Hindi/emoji names need ZWNJ/ZWJ
    to spell correctly, so refusing it loses nothing real. This also
    matches what already shipped (it was inside the old blanket `Cf`
    refusal), so choosing "refuse" is a non-regression as well as the more
    defensible default."""
    with pytest.raises(intake.IntakeError):
        intake._reject_display_spoofing("some label", "a­b.md")


@pytest.mark.parametrize(
    "name",
    [
        "doc1/می‌روم.md",  # Persian, real ZWNJ
        "doc1/\U0001f468‍\U0001f469‍\U0001f467.md",  # ZWJ family emoji
    ],
)
def test_zwnj_and_zwj_are_now_allowed(name, tmp_path):
    """N-4's actual point: entire writing systems (Persian, Hindi, ...)
    and emoji ZWJ sequences use ZWNJ/ZWJ as part of a word's/glyph's
    spelling -- refusing them outright, as the pre-round-3 blanket Cf
    check did, made those names unpublishable at all."""
    intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)  # must not raise


# ---- N-4(iii)/N-11 caveat (LOW-1)/LOW-2: one collision key ---------------


def test_zwnj_inserted_name_collides_with_the_plain_spelling(tmp_path):
    """N-4 correction (iii), the premise made true: NFC and NFKC both
    PRESERVE ZWNJ (measured), so allowing it through display-spoofing
    refusal would otherwise let 'report.md' and 'repor<ZWNJ>t.md' extract
    as two different files that render identically in a hub PR diff. The
    collision key strips Default_Ignorable characters (ZWNJ included)
    before comparing, so this collides instead of silently landing as two
    files."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name in ("doc1/report.md", "doc1/repor‌t.md"):
            info = tarfile.TarInfo(name)
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(buf.getvalue(), tmp_path)
    assert exc.value.status == 400


def test_vs16_inserted_name_collides_with_the_plain_spelling(tmp_path):
    """P44 (round 4): the same proof as ZWNJ's collision test, for the
    newly-allowed variation selector -- 'report.md' and
    'repor<VS16>t.md' must collide once VS16 is stripped, or allowing
    VS16 through `_reject_display_spoofing` would reopen the display-
    spoof risk the ZWNJ carve-out already closed by keying on the
    stripped form."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name in ("doc1/report.md", "doc1/repor️t.md"):
            info = tarfile.TarInfo(name)
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(buf.getvalue(), tmp_path)
    assert exc.value.status == 400


def test_mongolian_fvs_inserted_name_collides_with_the_plain_spelling(tmp_path):
    """P44 (round 4): same proof again for the newly-allowed Mongolian
    free variation selector."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name in ("doc1/report.md", "doc1/repor᠋t.md"):
            info = tarfile.TarInfo(name)
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(buf.getvalue(), tmp_path)
    assert exc.value.status == 400


def test_a_leading_dot_slash_no_longer_dodges_the_collision_check(tmp_path):
    """N-11 caveat / LOW-1: ['doc1/a.md', './doc1/a.md'] both resolve to
    the identical write target (Path() drops the leading './') but used to
    be accepted because the collision key compared the raw, un-normalized
    strings -- silently letting the second overwrite the first."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name in ("doc1/a.md", "./doc1/a.md"):
            info = tarfile.TarInfo(name)
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(buf.getvalue(), tmp_path)
    assert exc.value.status == 400


def test_a_case_colliding_pair_is_refused(tmp_path):
    """LOW-2: ['doc1/A.md', 'doc1/a.md'] used to be accepted outright with
    no refusal at intake time -- silent data loss on any case-folding
    consumer filesystem (Windows, default macOS)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name in ("doc1/A.md", "doc1/a.md"):
            info = tarfile.TarInfo(name)
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(intake.IntakeError) as exc:
        intake.safe_extract(buf.getvalue(), tmp_path)
    assert exc.value.status == 400

