"""`kb doctor`: health checks for a `.kb/`, its hub and its citations.

The checks live in `doctor.checks.*`, one module per concern; this package
re-exports them under their old names (`from strata_kb.doctor import
check_hub` keeps working) and holds `run()`, which assembles them by repo
kind for the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb import config as config_mod
from strata_kb import gitio
from strata_kb.doctor.checks.assets import (  # noqa: F401 -- re-exported
    ASSET_SIZE_WARN_BYTES,
    check_asset_store,
)
from strata_kb.doctor.checks.context import check_context
from strata_kb.doctor.checks.dev import check_dev_sync, check_hub_lag
from strata_kb.doctor.checks.hub import (  # noqa: F401 -- re-exported
    _fed_tree_digest,
    _ignoring_digests,
    _kb_tree_digest,
    check_federation_publish,
    check_hub,
    check_published_digests,
)
from strata_kb.doctor.checks.local import (  # noqa: F401 -- re-exported
    SOURCE_DIRS,
    _check_doc,
    check_config_credentials,
    check_kb,
    check_kind,
    check_source_dirs,
)
from strata_kb.doctor.checks.usage import (  # noqa: F401 -- re-exported
    _USAGE_HOOK,
    _has_usage_hook,
    check_usage_hooks,
    check_usage_log,
)
from strata_kb.doctor.issues import _CONFIG_READ_ERRORS, Issue, _flatten

if TYPE_CHECKING:
    from strata_kb.hub import HubHandle


@dataclass
class DoctorResult:
    """Everything `kb doctor` found once the hub is resolved. `stale` means
    a cited section changed (exit 2 when there is no error)."""

    issues: list[Issue]
    stale: bool


def run(
    kb_dir: Path, handle: HubHandle, *, context_text: str | None = None
) -> DoctorResult:
    """The `kb doctor` checks after `check_kind` passed and the hub resolved:
    the KB itself, the asset store, tracked sources and credentials, the
    kind's own checks (usage for ba/dev, hub and federation publish for a
    hub, sync and hub lag for dev), and the kb-context citations when
    `context_text` is given. Printing and exit codes stay in the CLI."""
    issues = check_kb(kb_dir) + check_asset_store(kb_dir, handle)
    try:
        repo_root = gitio.git_root(kb_dir.resolve())
    except gitio.GitError:
        repo_root = None  # not a git repo: nothing can be tracked
    if repo_root is not None:
        issues += check_source_dirs(repo_root)
        issues += check_config_credentials(kb_dir, repo_root)

    cfg_kind = ""
    try:
        cfg_kind = config_mod.load_config(kb_dir).kind
    except (*_CONFIG_READ_ERRORS, OSError) as exc:
        # check_kind (doctor.py) now catches this exact class set on this
        # exact file first and exits above -- this read can only still fire
        # on a TOCTOU race between the two reads (config.yaml changes or
        # vanishes between check_kind's read and this one). Kept as a
        # backstop for that race rather than removed, so a hit here still
        # reports instead of continuing with an empty kind and silently
        # skipping the kind-specific checks below.
        issues.append(
            Issue("error", f"could not read .kb/config.yaml: {_flatten(exc)}")
        )

    repo_id = config_mod.effective_repo_id("", kb_dir)
    if not repo_id:
        try:
            repo_id = gitio.git_root(kb_dir.resolve()).name
        except gitio.GitError as exc:
            # A reader .kb (any kind other than "hub") never consumes
            # repo_id below — see the "hub"-only uses further down — so an
            # undeterminable repo_id there is not this KB's problem to
            # report. Only a hub's own checks (check_hub, federation
            # publish) actually need it.
            if cfg_kind == "hub":
                issues.append(
                    Issue(
                        "error",
                        f"could not determine the repo id — .kb is not inside a "
                        f"git repo and repo_id is unset in config.yaml: "
                        f"{_flatten(exc)}",
                    )
                )
            repo_id = None

    if cfg_kind in ("ba", "dev"):
        issues += check_usage_log(kb_dir)
        issues += check_usage_hooks(kb_dir.resolve().parent)
    if cfg_kind == "hub":
        hub_issues, hub_stale = check_hub(
            kb_dir, handle, repo_id=repo_id, warn_untracked_index=True
        )
        issues += hub_issues
        try:
            source_root = gitio.git_root(kb_dir.resolve())
        except gitio.GitError as exc:
            issues.append(
                Issue(
                    "warning",
                    f"multi-tier checks skipped — .kb is not inside a git repo: {exc}",
                )
            )
        else:
            upstream = None
            if handle is not None and handle.root.resolve() != source_root.resolve():
                # A URL-configured hub resolves to a cache clone — compare
                # identities, not just paths: a cached clone of *this* repo
                # (same repo_id in its config) is still "self".
                try:
                    dest_rid = config_mod.load_config(handle.kb_dir).repo_id
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
                if not (repo_id and dest_rid and dest_rid == repo_id):
                    upstream = handle
            issues += check_federation_publish(source_root, upstream, repo_id)
    else:
        # The generated doc (dev `-code`, ba `-plan`) is rebuilt per branch
        # and CI publishes it, so it is left out of the snapshot compare.
        suffix = {"dev": "code", "ba": "plan"}.get(cfg_kind)
        generated = f"{repo_id}-{suffix}" if suffix and repo_id else None
        hub_issues, hub_stale = check_hub(
            kb_dir, handle, repo_id=repo_id, code_doc=generated
        )
        issues += hub_issues
        if cfg_kind == "dev":
            repo_root = kb_dir.resolve().parent
            issues += check_dev_sync(kb_dir, repo_root, repo_id)
            issues += check_hub_lag(kb_dir, repo_root, handle, repo_id)
    has_stale = False
    if context_text is not None:
        ctx_issues, results = check_context(context_text, handle)
        issues += ctx_issues
        has_stale = any(r.status == "stale" for r in results)
    return DoctorResult(issues=issues, stale=has_stale or hub_stale)
