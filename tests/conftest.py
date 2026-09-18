import os

# Typer force-enables Rich's colored/wrapped error rendering whenever
# GITHUB_ACTIONS is set (typer.rich_utils.FORCE_TERMINAL), which is meant to
# make CI log output readable but instead makes it non-deterministic for
# tests: Rich's option-name highlighter can split a flag like "--assistant"
# into two separately-styled spans with a reset code between them, so a
# plain `"--assistant" in result.output` substring check that passes locally
# fails only in CI. Must be set before typer.rich_utils is first imported
# (its FORCE_TERMINAL is computed once, at module import time) — hence
# first thing in this file, ahead of every other import.
os.environ.setdefault("_TYPER_FORCE_DISABLE_TERMINAL", "1")

import subprocess
from pathlib import Path

import pytest

from center_kb import models
from center_kb.mdutils import count_tokens, slice_section


class FakeEmbedder:
    """Deterministic 4-dimensional vector keyed on marker words — no real model needed.

    'corridor' shares an axis with 'airspace' so the semantic leg can find the
    airspace section from a query that contains no keyword matching FTS.
    """

    dim = 4
    name = "fake-4d"

    def embed(self, texts):
        out = []
        for t in texts:
            t = t.lower()
            out.append(
                [
                    1.0 if ("airspace" in t or "corridor" in t) else 0.0,
                    1.0 if "airway" in t else 0.0,
                    1.0 if "roster" in t else 0.0,
                    0.1,
                ]
            )
        return out


def pytest_addoption(parser):
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="also run the tests that download a real embedding model",
    )


@pytest.fixture(autouse=True)
def _no_real_embedder(request, monkeypatch):
    """search() now resolves default_embedder() eagerly on every query — unit tests
    must be hermetic: a dev machine with fastembed must not load/download the real
    model. Skipped for tests marked real_embedder or when running --run-slow."""
    if request.node.get_closest_marker("real_embedder") or request.config.getoption(
        "--run-slow"
    ):
        yield
        return
    from center_kb import embed

    monkeypatch.setattr(embed, "default_embedder", lambda: None)
    yield


TABLE = "| Code | Meaning |\n|---|---|\n| P | Prohibited |\n| R | Restricted |"

L2_CONTENT = f"""## 1.1 Airspace Records

Condensed: airspace record structure with designation and type fields.

{TABLE}

## 1.2 Airway Records

Condensed: airway record structure, route identifiers.
"""

L3_CONTENT = f"""## 1.1 Airspace Records

Full raw text about airspace records. Designation, type, multiple code, level. Each airspace record carries the designation of the airspace, its type code from the table below, a multiple code that separates overlapping volumes, and the lower and upper level fields that bound it vertically. The structure is fixed-width and every field is mandatory unless noted.

{TABLE}

## 1.2 Airway Records

Full raw text about airway records and route identifiers. An airway record names the route identifier, the sequence number of each fix along the route, the level and direction restrictions that apply between consecutive fixes, and the cruising table used along the segment. Records are ordered by route identifier then sequence number.
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
                # Real counts, not the 0/0 default -- doctor now recounts L2/L3
                # tokens and reports drift (M9), so a fixture claiming to be a
                # clean KB must carry the counts its own content would produce.
                tokens=models.SectionTokens(
                    l2=count_tokens(slice_section(L2_CONTENT, "1.1")),
                    l3=count_tokens(slice_section(L3_CONTENT, "1.1")),
                ),
            ),
            models.SectionEntry(
                id="1.2",
                title="Airway Records",
                summary="Airway record structure and route identifiers.",
                status="summarized",
                file="ch1-records",
                tokens=models.SectionTokens(
                    l2=count_tokens(slice_section(L2_CONTENT, "1.2")),
                    l3=count_tokens(slice_section(L3_CONTENT, "1.2")),
                ),
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
            "airspace record structure with an amended multiple code field.",
        ),
        encoding="utf-8",
    )
    manifest_path = fixture_kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].summary = (
        "Airspace record structure: designation, type, multiple code."
    )
    # The amendment above changed §1.1's L2 body -- recount, or doctor's
    # stale-token check (M9) flags this fixture's own "clean" state as drift.
    manifest.sections[0].tokens.l2 = count_tokens(
        slice_section(l2.read_text(encoding="utf-8"), "1.1")
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


@pytest.fixture
def hub_with_origin(hub_worktree: Path, run_git, tmp_path: Path) -> Path:
    """hub_worktree, plus a bare 'origin' remote it has already pushed to —
    for tests that need to tell "no remote" apart from "nothing to push"."""
    origin = tmp_path / "hub-origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(hub_worktree, "remote", "add", "origin", str(origin))
    run_git(hub_worktree, "push", "-u", "origin", "HEAD")
    return hub_worktree


@pytest.fixture
def make_upload():
    """A .tar.gz holding a minimal one-doc KB for a given repo-id -- for tests
    that call intake.intake_publish directly with a synthetic upload."""
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


@pytest.fixture
def intake_cfg(hub_with_origin, tmp_path, monkeypatch):
    """IntakeConfig wired to hub_with_origin (hub_worktree + a real bare
    'origin' remote already pushed to), with the GitHub App calls faked out.

    For tests that call intake.intake_publish directly, bypassing the OIDC
    HTTP route -- test_intake_http.py has its own `intake_cfg` (a different
    fixture, local to that module, built on its own hub_with_registry +
    keypair fixtures for exercising the authenticated /intake/publish route)
    which this one does not replace.
    """
    from center_kb import ghapp, intake

    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")

    def fake_http(req):
        import json

        url = req.full_url
        if req.get_method() == "GET" and url.endswith("/installation"):
            return 200, json.dumps({"id": 9}).encode()
        if req.get_method() == "POST" and url.endswith("/access_tokens"):
            return 201, json.dumps({"token": "fake-installation-token"}).encode()
        if req.get_method() == "POST" and url.endswith("/pulls"):
            return 201, json.dumps({"html_url": "https://github.com/acme/hub/pull/1"}).encode()
        raise AssertionError(f"unexpected http call in intake_cfg fixture: {req.get_method()} {url}")

    return intake.IntakeConfig(
        hub_ref=str(hub_with_origin),
        audience="https://kb.test",
        creds=ghapp.AppCreds(app_id="1", private_key_pem="unused-fake-http"),
        http=fake_http,
        push_via_token_url=False,
    )


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
        l3="## 5.3 Restrictive Airspace\n\nVerbatim: Full raw restrictive airspace text.\n",
    )
    write_federation_index(fed)
    run_git(hub, "init")
    run_git(hub, "config", "user.name", "test")
    run_git(hub, "config", "user.email", "test@test.local")
    run_git(hub, "add", "-A")
    run_git(hub, "commit", "-m", "hub v1")
    return hub


# ==========================================================================
# Web /ui session fixtures (M4, Task 9) — shared by tests/test_web_session.py
# and every web-lane task that follows it (10-13). Function-scoped: Task 11
# shares one rate-limiter instance between the login form and the
# Authorization path (5-attempt window) -- a session/module-scoped client
# would leak 429s from one test into the next.
# ==========================================================================


@pytest.fixture
def token() -> str:
    return "s3cr3t-token-abcdefgh"


@pytest.fixture
def hub_dir(fed_hub: Path) -> Path:
    return fed_hub


@pytest.fixture
def web_client(hub_dir: Path, token: str):
    """A TestClient over the full app (auth middleware + /api + /ui + /mcp
    mount point), not just ui.build_routes -- unauthenticated /ui* requests
    must actually redirect to /ui/login, which only the middleware enforces.

    Used as a context manager so Starlette's lifespan startup/shutdown
    actually runs (create_app(mcp_server=None) has no real lifespan work
    today, so this is a no-op in practice -- but a fixture every later
    web-lane task inherits must not silently skip it)."""
    from starlette.testclient import TestClient

    from center_kb.mcp import ServerConfig
    from center_kb.web.app import create_app

    config = ServerConfig(kb_dir=hub_dir / ".kb", hub=str(hub_dir))
    with TestClient(create_app(config, token)) as c:
        yield c


@pytest.fixture
def web_client_https(hub_dir: Path, token: str):
    """web_client, but the request presents as https on the wire -- for
    cookie_is_secure's request.url.scheme branch (Task 10 needs this exact
    fixture name)."""
    from starlette.testclient import TestClient

    from center_kb.mcp import ServerConfig
    from center_kb.web.app import create_app

    config = ServerConfig(kb_dir=hub_dir / ".kb", hub=str(hub_dir))
    with TestClient(
        create_app(config, token), base_url="https://testserver"
    ) as c:
        yield c


@pytest.fixture
def web_client_logged_in(web_client, token: str):
    """web_client, already carrying a real session cookie from a genuine
    /ui/login round trip."""
    web_client.post("/ui/login", data={"token": token}, follow_redirects=False)
    return web_client


def make_stale(fed_hub: Path) -> None:
    """Edit a published L2 file in-place, after the block that pins it was
    built — the recipe every stale-ref test needs to make a still-resolving
    ref report as stale. Shared here (rather than copied into every test
    module that needs it) because `test_ticketlint.py`, `test_cli_ticket.py`
    and `test_cli_mission.py` all need the identical mutation."""
    l2 = fed_hub / "federation" / "icao-kb" / "icao-annex-2" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8") + "\nEdited after publish.\n",
        encoding="utf-8",
    )


# ==========================================================================
# The undiscardable hub cache (Ruling P49, Wave G fix round 5)
# ==========================================================================
#
# `hub._discard_cache` is `shutil.rmtree` and nothing else, so "a hub cache
# that cannot be discarded" has to be produced by making rmtree lose. Six
# tests across five files need exactly that, and every one of them used to
# hand-roll the SAME Windows-only recipe -- open a file handle inside the
# clone -- and then hand-roll a `skipif(sys.platform != "win32")` beside it
# (or, in two cases, forget to).
#
# That was the wrong shape twice over. Ruling P49: *the behaviour under test
# is platform-independent; only the mechanism for making the cache
# undiscardable is platform-specific.* "A hub cache that cannot be discarded
# produces one clean message and a non-zero exit, not a traceback" is true
# on every platform this ships to, and `_gate.yml` T1 runs three of its five
# legs on ubuntu-latest while the Dockerfile targets Linux -- so skipping
# there left the platform the product actually runs on uncovered, and the
# round-4 re-review measured the unguarded ones as a hard CI red rather than
# a vacuous pass.
#
# Measured on real Linux (python:3.11-slim, uid 1000, Wave G fix round 5 --
# `hub.resolve_hub` driven end to end against a real git legacy cache):
#
#   open file handle held inside the cache  -> rmtree SUCCEEDS  (no GitError)
#   read-only parent directory              -> GitError, cache named
#   neither (control)                       -> rmtree SUCCEEDS
#
# POSIX does have a mechanism; it is just not the Windows one. Unlinking a
# directory ENTRY needs write permission on the DIRECTORY, not on the file,
# and `_clear_readonly_and_retry` chmods the file, so its retry cannot help
# -- exactly the shape the Windows handle produces. So the tests are now
# platform-neutral and the mechanism is chosen per platform, which is what
# P49 asks for.
#
# The one case with no mechanism at all is POSIX as root: root bypasses
# discretionary access control, so the read-only directory is not read-only
# for it (measured in the same container as uid 0: rmtree SUCCEEDS). That,
# and only that, skips -- once, here, for every caller. GitHub Actions'
# ubuntu-latest runs as a non-root user, so all three Linux legs really run.
_NO_POSIX_MECHANISM_AS_ROOT = (
    "a hub cache that cannot be discarded has no mechanism on POSIX when "
    "running as root: rmtree fails on POSIX because the entry's PARENT "
    "directory is not writable, and root bypasses that check (measured, "
    "python:3.11-slim as uid 0: rmtree succeeds where it fails as uid "
    "1000). Windows uses an open file handle instead and is unaffected. "
    "CI's ubuntu-latest legs run as a non-root user, so they DO run this "
    "-- only a root shell (a bare container) skips it."
)


@pytest.fixture
def undiscardable_hub_cache():
    """Context manager: make `shutil.rmtree(cache)` -- and so
    `hub._discard_cache(cache)` -- fail, by whichever mechanism this OS has.

    Used by every test that needs `resolve_hub` to raise `gitio.GitError`
    from a legacy cache it cannot remove:

      * tests/test_hub.py::test_discard_cache_failure_names_the_cache_and_the_fix
      * tests/test_cli_errors.py::test_locked_hub_cache_discard_is_one_line_not_a_traceback
      * tests/test_cli_errors.py::test_doctor_locked_hub_cache_discard_is_one_line_not_a_traceback
      * tests/test_intake_core.py::test_resolve_hub_or_503_converts_a_locked_cache_into_a_503_not_a_500
      * tests/test_web_app.py::test_hub_locked_cache_returns_503_not_a_crash

    (`tests/test_mcp.py::test_hub_locked_cache_returns_guidance_not_a_crash`
    is NOT one of them, whatever earlier skip reasons in this tree claimed:
    it fakes `resolve_hub` outright and is platform-independent already.
    `tests/test_intake_http.py` and `tests/test_intake_startup.py` each hold
    one more instance of the hand-rolled recipe; they belong to another
    task's file scope and are untouched -- they should adopt this fixture.)

    The probe it plants is the real-world cause the error message names:
    `<cache>/.kb-work/search.sqlite3`, the file a `kb query`/MCP/web process
    holds open.
    """
    import contextlib
    import os
    import sys

    if sys.platform != "win32" and getattr(os, "geteuid", lambda: 1)() == 0:
        pytest.skip(_NO_POSIX_MECHANISM_AS_ROOT)

    @contextlib.contextmanager
    def _undiscardable(cache: Path):
        probe_dir = cache / ".kb-work"
        probe_dir.mkdir(parents=True, exist_ok=True)
        probe = probe_dir / "search.sqlite3"
        probe.write_text("x", encoding="utf-8")
        if sys.platform == "win32":
            handle = probe.open("r", encoding="utf-8")
            try:
                yield cache
            finally:
                handle.close()
        else:
            os.chmod(probe_dir, 0o500)
            try:
                yield cache
            finally:
                # rmtree got partway: restore write permission either way,
                # or tmp_path teardown inherits the failure.
                if probe_dir.is_dir():
                    os.chmod(probe_dir, 0o700)

    return _undiscardable
