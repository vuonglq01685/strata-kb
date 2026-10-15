"""Checks for dev repos: the -code document and hub lag."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb import gitio
from strata_kb.doctor.issues import Issue

if TYPE_CHECKING:
    from strata_kb.codeingest.hublag import LagReport
    from strata_kb.hub import HubHandle

_DB_FLAG_RE = re.compile(r"kb code-ingest[^\n]*--db")


def check_dev_sync(kb_dir: Path, repo_root: Path, repo_id: str | None) -> list[Issue]:
    """Dev repo: what makes local `-code` differ from CI's, and the one
    migration step a gitignore line cannot do."""
    from strata_kb.codeingest import sync

    issues: list[Issue] = []
    try:
        workflow = (repo_root / sync.KB_CODE_WORKFLOW).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        workflow = ""
    if _DB_FLAG_RE.search(workflow):
        issues.append(
            Issue(
                "warning",
                "kb-code.yml passes --db to kb code-ingest — move the paths to "
                "`code_ingest.db` in .kb/config.yaml before re-running "
                "`kb init --kind dev`, which overwrites the workflow",
            )
        )
    pin_note = sync.version_note(repo_root)
    if pin_note:
        issues.append(Issue("warning", pin_note))
    if repo_id:
        try:
            rel = (
                (kb_dir.resolve() / f"{repo_id}-code")
                .relative_to(repo_root.resolve())
                .as_posix()
            )
        except ValueError:
            rel = ""
        if rel:
            try:
                proc = gitio._run(repo_root, "ls-files", "--", rel)
            except FileNotFoundError:
                proc = None
            if proc is not None and proc.returncode == 0 and proc.stdout.strip():
                issues.append(
                    Issue(
                        "warning",
                        f"{rel} is tracked by git but is derived on demand — run "
                        f"`git rm -r --cached {rel}` and commit (a .gitignore line "
                        "does not untrack files)",
                    )
                )
    return issues


def check_code_extra() -> list[Issue]:
    """Dev repo: without the `code` extra the route/page/job/symbol sections
    are all `not scanned`, and the ticket gate can never accept a [NEW]."""
    from strata_kb.codeingest.extractors import _ts

    if _ts.available():
        return []
    return [
        Issue(
            "warning",
            "strata-kb[code] is not installed — routes, pages, jobs and symbols "
            "will be 'not scanned'; pip install \"strata-kb[code]\"",
        )
    ]


def check_hub_lag(
    kb_dir: Path, repo_root: Path, handle: HubHandle | None, repo_id: str | None
) -> list[Issue]:
    """Dev repo: is the hub's -code what the default branch would publish?"""
    if handle is None or not repo_id:
        return []
    from strata_kb.codeingest import hublag

    report = hublag.check(repo_root, kb_dir, handle.federation_dir, repo_id)
    return lag_issues(report, repo_id)


def lag_issues(report: LagReport, repo_id: str) -> list[Issue]:
    if report.state == "in-sync":
        return []
    if report.state == "unknown":
        return [Issue("warning", f"hub lag not judged — {report.reason}")]
    parts = []
    if report.only_on_main:
        parts.append("only on main: " + ", ".join(report.only_on_main))
    if report.only_on_hub:
        parts.append("only on the hub: " + ", ".join(report.only_on_hub))
    if report.changed:
        parts.append("changed: " + ", ".join(report.changed))
    return [
        Issue(
            "warning",
            f"hub {repo_id}-code lags {report.ref} (as of {report.ref_date}) — "
            f"{'; '.join(parts)} — check for a pending -code PR on the hub, or the "
            "latest kb-code.yml run (run `kb publish` to publish it)",
        )
    ]
