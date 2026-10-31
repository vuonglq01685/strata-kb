"""Demo hub + full web app for the mobile UI browser checks.

Run from the repo root:
    .venv/bin/python scripts/ui_demo_server.py --port 8765
Prints `READY http://127.0.0.1:<port> admin <password>` once listening.
"""

import argparse
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

from strata_kb import ghapp, gitio, models
from strata_kb.federation import write_federation_index
from strata_kb.intake import IntakeConfig
from strata_kb.mcp import ServerConfig
from strata_kb.serving.accounts import Accounts
from strata_kb.web.app import create_app
from tests.conftest import make_fed_entry
from tests.test_planingest import context_block
from tests.test_planstatus import publish_ba, publish_svc

TOKEN = "demo-token"  # noqa: S105
TABLE = "| Code | Meaning |\n|---|---|\n| P | Prohibited |\n| R | Restricted |"
DEMO_L2 = (
    f"## 1.1 Airspace Records\n\nCondensed: airspace record structure.\n\n{TABLE}\n"
)
DEMO_L3 = (
    f"## 1.1 Airspace Records\n\nFull raw text about airspace records.\n\n{TABLE}\n"
)
# registry rows: an unbreakable repo_id, a workflow pin, auto-merge on
REGISTRY = """\
repos:
  acme/aaa-long:
    repo_id: my_very_long_repository_identifier_v2_0123456789abcdef
    kind: dev
    auto_merge: true
  acme/pinned:
    repo_id: pinned-kb
    kind: dev
    workflow: owner/repo/.github/workflows/kb-code.yml@refs/heads/main
"""
LONG_DOC = "very-long-document-identifier-without-any-breaks-0123456789"
LONG_SEC = "appendix-b.long-slug-section-identifier-0123456789"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "demo",
    "GIT_AUTHOR_EMAIL": "demo@demo.local",
    "GIT_COMMITTER_NAME": "demo",
    "GIT_COMMITTER_EMAIL": "demo@demo.local",
    # fixed dates: the commit sha and date show in the top bar, so every run must match
    "GIT_AUTHOR_DATE": "2026-10-30T12:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-10-30T12:00:00+00:00",
}


def git(root: Path, *args: str) -> None:
    env = {**os.environ, **GIT_ENV}
    subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
    )


def add_sections(fed: Path, repo: str, doc: str, ids: list[str]) -> None:
    """Append sections to a make_fed_entry manifest (as tests' _add_section)."""
    path = fed / repo / doc / "_manifest.yaml"
    manifest = models.load_yaml_model(path, models.Manifest)
    for sid in ids:
        manifest.sections.append(
            models.SectionEntry(
                id=sid,
                title=f"Section {sid}",
                summary=f"Summary of section {sid}.",
                status="summarized",
                file="ch1",
            )
        )
    models.save_yaml_model(path, manifest)


def build_hub(root: Path) -> Path:
    hub = root / "kb-hub"
    (hub / ".kb").mkdir(parents=True)
    models.save_yaml_model(hub / ".kb" / "index.yaml", models.KBIndex())
    fed = hub / "federation"
    make_fed_entry(
        fed, "icao-kb", "icao-annex-2", tags=["icao", "airspace"],
        sec_id="1.1", sec_title="Airspace Records",
        sec_summary="Airspace record structure: designation, type, level.",
        l2="## 1.1 Airspace Records\n\nCondensed: airspace designation and type fields.\n",
        l3="## 1.1 Airspace Records\n\nFull raw text about airspace designation.\n",
    )  # fmt: skip
    make_fed_entry(
        fed, "arinc-kb", "arinc-424", tags=["arinc424"],
        sec_id="5.3", sec_title="Restrictive Airspace",
        sec_summary="Restrictive airspace: designation, type, multiple code.",
        l2="## 5.3 Restrictive Airspace\n\nCondensed: restrictive airspace codes.\n",
        l3="## 5.3 Restrictive Airspace\n\nVerbatim: Full raw restrictive airspace text.\n",
    )  # fmt: skip
    make_fed_entry(
        fed, "demo-kb", "demo-doc", title="Demo Document",
        tags=["demo", "airspace"], summary="Demo aviation data spec.",
        sec_id="1.1", sec_title="Airspace Records",
        sec_summary="Airspace record structure: designation, type, level.",
        l2=DEMO_L2, l3=DEMO_L3,
    )  # fmt: skip
    make_fed_entry(
        fed, "long-kb", LONG_DOC, title=LONG_DOC, summary="Long identifiers.",
        sec_id=LONG_SEC, sec_title="Long slug section",
        sec_summary="Section with an unbreakable id.",
    )  # fmt: skip
    make_fed_entry(
        fed, "many-kb", "many-doc", title="Many Tags And Sections",
        tags=[f"tag-{n:02d}" for n in range(60)], summary="60 tags, 40 sections.",
    )  # fmt: skip
    add_sections(fed, "many-kb", "many-doc", [f"1.{n}" for n in range(2, 41)])
    (fed / "registry.yaml").write_text(REGISTRY, encoding="utf-8", newline="\n")
    write_federation_index(fed)
    git(hub, "init")
    git(hub, "add", "-A")
    git(hub, "commit", "-m", "demo hub")
    # the plan's context block pins the hub's HEAD, so it needs a commit first
    publish_ba(hub, root / "ba-one", context_block(hub))
    publish_svc(hub)
    write_federation_index(fed)
    git(hub, "add", "-A")
    git(hub, "commit", "-m", "demo plans")
    # an origin remote (never pushed to: registry_push is a no-op) makes /ui/registry editable
    origin = root / "hub-origin.git"
    git(root, "init", "--bare", "-b", gitio.current_branch(hub), str(origin))
    git(hub, "remote", "add", "origin", str(origin))
    git(hub, "push", "-u", "origin", "HEAD")
    git(hub, "remote", "set-head", "origin", gitio.current_branch(hub))
    return hub


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    port = parser.parse_args().port
    hub = build_hub(Path(tempfile.mkdtemp(prefix="ui-demo-")))
    password = secrets.token_urlsafe(12)
    Accounts(hub / ".kb-auth" / "users.db").add("admin", password, "admin")
    config = ServerConfig(kb_dir=hub / ".kb", hub=str(hub))
    intake = IntakeConfig(  # fake creds: only gates the registry page's edit forms
        hub_ref=str(hub),
        audience="https://demo.invalid",
        creds=ghapp.AppCreds(app_id="1", private_key_pem="unused"),
    )
    app = create_app(config, TOKEN, intake_cfg=intake, registry_push=lambda work, branch: None)
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning"))
    original_startup = server.startup

    async def startup(sockets=None):
        await original_startup(sockets)
        print(f"READY http://127.0.0.1:{port} admin {password}", flush=True)

    server.startup = startup
    server.run()


if __name__ == "__main__":
    main()
