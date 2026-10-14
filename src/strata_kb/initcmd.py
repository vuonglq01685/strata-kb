"""initcmd — `kb init`: scaffold a repo as a hub, child, BA or dev KB.

`init_repo()` writes the template map for the kind (`template_map()`): it
creates missing files and refreshes changed scaffold templates, but leaves
PROTECTED_FILES alone unless forced and only ever merges into `.gitignore`.
It also appends `kind:`, `langs:` and `asset_store:` to `.kb/config.yaml`
without rewriting what is there, and creates the BA/dev `*.local.md` overrides
once. Templates live under `strata_kb/templates/init/`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from strata_kb import conventions, impltidy

KIND_HUB = "hub"
KIND_CHILD = "child"
KIND_BA = "ba"
KIND_DEV = "dev"
KINDS = (KIND_HUB, KIND_CHILD, KIND_BA, KIND_DEV)

# target relative path -> template resource name under templates/init/
COMMON_TEMPLATES: dict[str, str] = {
    ".kb/index.yaml": "index.yaml",
    # Both spellings: README once said `sources/`, the scaffold `source/`, and
    # whoever followed the README had no ignore rule.
    "source/.gitignore": "source-gitignore.txt",
    "sources/.gitignore": "source-gitignore.txt",
    ".claude/skills/kb-summarize/SKILL.md": "claude-skill-kb-summarize.md",
    ".claude/commands/kb-summarize.md": "claude-command-kb-summarize.md",
    ".github/instructions/kb-summarize.instructions.md": "copilot-kb-summarize.instructions.md",
    ".claude/skills/kb-ingest/SKILL.md": "claude-skill-kb-ingest.md",
    ".github/prompts/kb-ingest.prompt.md": "copilot-kb-ingest.prompt.md",
    ".claude/skills/kb-publish/SKILL.md": "claude-skill-kb-publish.md",
    ".github/prompts/kb-publish.prompt.md": "copilot-kb-publish.prompt.md",
    ".github/workflows/kb-publish.yml": "kb-publish.yml",
    ".cursor/commands/kb-ingest.md": "cursor-kb-ingest.md",
    ".cursor/commands/kb-publish.md": "cursor-kb-publish.md",
    ".cursor/commands/kb-summarize.md": "cursor-kb-summarize.md",
    ".cursor/rules/kb-summarize.mdc": "cursor-kb-summarize.mdc",
    ".claude/skills/kb-docker-setup/SKILL.md": "claude-skill-kb-docker-setup.md",
    ".claude/commands/kb-docker-setup.md": "claude-command-kb-docker-setup.md",
    ".github/prompts/kb-docker-setup.prompt.md": "copilot-kb-docker-setup.prompt.md",
    ".cursor/commands/kb-docker-setup.md": "cursor-kb-docker-setup.md",
    ".claude/skills/kb-approve/SKILL.md": "claude-skill-kb-approve.md",
    ".claude/commands/kb-approve.md": "claude-command-kb-approve.md",
    ".github/prompts/kb-approve.prompt.md": "copilot-kb-approve.prompt.md",
    ".cursor/commands/kb-approve.md": "cursor-kb-approve.md",
    ".claude/skills/kb-init/SKILL.md": "claude-skill-kb-init.md",
    ".claude/commands/kb-init.md": "claude-command-kb-init.md",
    ".github/prompts/kb-init.prompt.md": "copilot-kb-init.prompt.md",
    ".cursor/commands/kb-init.md": "cursor-kb-init.md",
}

# The kinds that reach the hub over HTTP MCP. `COMMON_TEMPLATES` cannot hold
# these: that map is the hub+child merge, and the hub serves MCP over stdio
# from its own `.mcp.json` — it has nothing to connect to. Spread into
# CHILD/BA/DEV instead.
MCP_CLIENT_TEMPLATES: dict[str, str] = {
    ".claude/skills/kb-mcp-setup/SKILL.md": "claude-skill-kb-mcp-setup.md",
    ".claude/commands/kb-mcp-setup.md": "claude-command-kb-mcp-setup.md",
    ".github/prompts/kb-mcp-setup.prompt.md": "copilot-kb-mcp-setup.prompt.md",
    ".cursor/commands/kb-mcp-setup.md": "cursor-kb-mcp-setup.md",
}

HUB_TEMPLATES: dict[str, str] = {
    ".kb/config.yaml": "config-hub.yaml",
    ".gitignore": "hub-gitignore.txt",
    ".gitattributes": "gitattributes.txt",
    "docker-compose.yml": "docker-compose-hub.yml",
    ".env.example": "env.example",
    "federation/README.md": "federation-README.md",
    ".mcp.json": "mcp-hub.json",
    "QUICKSTART.md": "QUICKSTART-hub.md",
    ".cursor/mcp.json": "mcp-hub.json",
    ".claude/skills/kb-code-sync/SKILL.md": "claude-skill-kb-code-sync.md",
    ".claude/commands/kb-code-sync.md": "claude-command-kb-code-sync.md",
    ".github/prompts/kb-code-sync.prompt.md": "copilot-kb-code-sync.prompt.md",
    ".cursor/commands/kb-code-sync.md": "cursor-kb-code-sync.md",
}

# Filled in by the child-scaffold task; kept separate so hub and child can
# diverge artifact-by-artifact.
CHILD_TEMPLATES: dict[str, str] = {
    **MCP_CLIENT_TEMPLATES,
    ".kb/config.yaml": "config-child.yaml",
    ".gitattributes": "gitattributes-child.txt",
    "docker-compose.yml": "docker-compose-child.yml",
    ".mcp.json": "mcp-child.json",
    "QUICKSTART.md": "QUICKSTART-child.md",
    ".cursor/mcp.json": "cursor-mcp-child.json",
}

# Kind `ba` — requirements repo. It consumes the shared KB (via the
# ba-ticket-author skill + MCP) and versions tickets; it authors no KB
# documents itself, so it carries none of the ingest/summarize machinery.
# It publishes exactly one document, its generated `<repo_id>-plan`, so it
# gets the kb-publish skill and workflow. Deliberately NOT merged with
# COMMON_TEMPLATES: a ba repo gets exactly this set, nothing from the
# hub/child authoring stack.
BA_TEMPLATES: dict[str, str] = {
    **MCP_CLIENT_TEMPLATES,
    ".kb/config.yaml": "config-ba.yaml",
    ".mcp.json": "mcp-child.json",
    ".claude/settings.json": "claude-settings-usage.json",
    ".cursor/mcp.json": "cursor-mcp-child.json",
    ".gitattributes": "gitattributes-child.txt",
    ".claude/skills/kb-publish/SKILL.md": "claude-skill-kb-publish.md",
    ".github/prompts/kb-publish.prompt.md": "copilot-kb-publish.prompt.md",
    ".cursor/commands/kb-publish.md": "cursor-kb-publish.md",
    ".github/workflows/kb-publish.yml": "kb-publish-ba.yml",
    ".github/workflows/kb-publish-request.yml": "kb-publish-request.yml",
    ".claude/skills/ba-ticket-author/SKILL.md": "claude-skill-ba-ticket-author.md",
    ".claude/commands/ba-ticket-author.md": "claude-command-ba-ticket-author.md",
    ".github/prompts/ba-ticket-author.prompt.md": "copilot-ba-ticket-author.prompt.md",
    ".cursor/commands/ba-ticket-author.md": "cursor-ba-ticket-author.md",
    ".claude/skills/ba-answer-questions/SKILL.md": "claude-skill-ba-answer-questions.md",
    ".claude/commands/ba-answer-questions.md": "claude-command-ba-answer-questions.md",
    ".github/prompts/ba-answer-questions.prompt.md": "copilot-ba-answer-questions.prompt.md",
    ".cursor/commands/ba-answer-questions.md": "cursor-ba-answer-questions.md",
    ".claude/skills/ba-mission-plan/SKILL.md": "claude-skill-ba-mission-plan.md",
    ".claude/commands/ba-mission-plan.md": "claude-command-ba-mission-plan.md",
    ".github/prompts/ba-mission-plan.prompt.md": "copilot-ba-mission-plan.prompt.md",
    ".cursor/commands/ba-mission-plan.md": "cursor-ba-mission-plan.md",
    ".claude/skills/ba-bug-report/SKILL.md": "claude-skill-ba-bug-report.md",
    ".claude/commands/ba-bug-report.md": "claude-command-ba-bug-report.md",
    ".github/prompts/ba-bug-report.prompt.md": "copilot-ba-bug-report.prompt.md",
    ".cursor/commands/ba-bug-report.md": "cursor-ba-bug-report.md",
    ".claude/skills/sa-ticket-ground/SKILL.md": "claude-skill-sa-ticket-ground.md",
    ".claude/commands/sa-ticket-ground.md": "claude-command-sa-ticket-ground.md",
    ".github/prompts/sa-ticket-ground.prompt.md": "copilot-sa-ticket-ground.prompt.md",
    ".cursor/commands/sa-ticket-ground.md": "cursor-sa-ticket-ground.md",
    "docs/tickets/TEMPLATE.md": "ticket-template.md",
    "docs/tickets/BUG-TEMPLATE.md": "bug-template.md",
    "docs/missions/TEMPLATE.md": "mission-template.md",
    "docs/ac-quality.md": "ac-quality.md",
    "docs/review-rubric.md": "review-rubric.md",
    "tickets/.gitkeep": "gitkeep.txt",
    "missions/.gitkeep": "gitkeep.txt",
    ".github/workflows/kb-ticket-lint.yml": "kb-ticket-lint.yml",
    ".github/workflows/kb-doctor.yml": "kb-doctor.yml",
    "QUICKSTART-BA.md": "QUICKSTART-ba.md",
}

# Created once, never refreshed: the BA's own review criteria. Deliberately
# NOT in BA_TEMPLATES (that map is create-or-refresh) and NOT in
# PROTECTED_FILES (that set means "never written", which would freeze the
# BASE rubric at whatever version first scaffolded a repo). Same contract
# `conventions.scaffold_conventions` gives the dev side's
# `docs/conventions/<lang>.local.md`.
BA_LOCAL_OVERRIDES: dict[str, str] = {
    "docs/review-rubric.local.md": "review-rubric-local-stub.md",
    "docs/ac-quality.local.md": "ac-quality-local-stub.md",
}


# A template whose last line is this directive is a stub: its own frontmatter
# (and, for some, a heading) followed by a body shared with the other tools'
# copies of the same skill, kept once under templates/init/bodies/ (1.16.0).
_INCLUDE_RE = re.compile(r"<!-- strata-kb:include (bodies/[a-z0-9-]+\.md) -->\n\Z")


def read_template(name: str) -> str:
    """The text `kb init` writes for template `name`, shared body included."""
    base = resources.files("strata_kb").joinpath("templates/init")
    text = base.joinpath(name).read_text(encoding="utf-8")
    match = _INCLUDE_RE.search(text)
    if match is None:
        return text
    return text[: match.start()] + base.joinpath(match.group(1)).read_text(
        encoding="utf-8"
    )


def _init_template_text(name: str) -> str:
    return read_template(name)


def _scaffold_local_overrides(
    target: Path, report: InitReport, overrides: dict[str, str]
) -> None:
    """Create each `.local.md` override once, then never touch it again.
    The base file it overrides stays package-owned and keeps being
    refreshed, so a repo receives improved criteria on upgrade without
    losing the local overrides it wrote."""
    for rel, resource_name in overrides.items():
        dest = target / rel
        if dest.exists():
            report.skipped.append(f"{rel} (local overrides — never refreshed)")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            _init_template_text(resource_name), encoding="utf-8", newline="\n"
        )
        report.created.append(rel)


def scaffold_ba_local_overrides(target: Path, report: InitReport) -> None:
    """Create the BA repo's `.local.md` override files."""
    _scaffold_local_overrides(target, report, BA_LOCAL_OVERRIDES)


# Created once, never refreshed — the dev repo's own merge-risk criteria.
# Same contract as BA_LOCAL_OVERRIDES: the BASE rubric stays package-owned
# and keeps being refreshed, so a repo gets improved criteria on upgrade
# without losing the stack-specific ones it wrote.
DEV_LOCAL_OVERRIDES: dict[str, str] = {
    "docs/pr-review-rubric.local.md": "pr-review-rubric-local-stub.md",
}


def scaffold_dev_local_overrides(target: Path, report: InitReport) -> None:
    """Create the dev repo's `.local.md` override."""
    _scaffold_local_overrides(target, report, DEV_LOCAL_OVERRIDES)


# Kind `dev` — product code repo. It consumes the shared KB while implementing
# BA tickets and publishes knowledge about its OWN source code. Like
# BA_TEMPLATES this is deliberately NOT merged with COMMON_TEMPLATES: a dev
# repo never ingests outside documents, so it carries none of the ingest/docker
# stack.
DEV_TEMPLATES: dict[str, str] = {
    **MCP_CLIENT_TEMPLATES,
    ".kb/config.yaml": "config-dev.yaml",
    ".kb/index.yaml": "index.yaml",
    # A dev repo publishes .kb/ (its own source knowledge) exactly like a
    # child does, so it needs the same hashed-tree-vs-CRLF-normalisation
    # exemption.
    ".gitattributes": "gitattributes-child.txt",
    ".mcp.json": "mcp-child.json",
    ".claude/settings.json": "claude-settings-usage.json",
    ".cursor/mcp.json": "cursor-mcp-child.json",
    "docs/impl/.gitkeep": "gitkeep.txt",
    "docs/impl/.gitignore": "impl-gitignore.txt",
    "QUICKSTART-DEV.md": "QUICKSTART-dev.md",
    ".github/workflows/kb-code.yml": "kb-code.yml",
    # The PR evidence gate. The template is the section
    # list dev-handover already assembles; the workflow makes it a required
    # check; the document names the four TDD exemption categories a plan's
    # `Exempt:` lines may use.
    ".github/pull_request_template.md": "pull-request-template.md",
    ".github/workflows/kb-pr-lint.yml": "kb-pr-lint.yml",
    ".github/workflows/kb-doctor.yml": "kb-doctor.yml",
    "docs/tdd-exemptions.md": "tdd-exemptions.md",
    "docs/pr-review-rubric.md": "pr-review-rubric.md",
    **{
        path: resource
        for skill in (
            "dev-implement-ticket",
            "dev-design",
            "dev-plan",
            "dev-execute",
            "dev-handover",
            # The one-time bootstrap skill. Added to this tuple (not to the
            # tests' DEV_WORKFLOW_SKILLS lists — it implements no ticket, so
            # the ticket-shaped SHARED-* canon doesn't apply to it) so it gets
            # the same four-way wrapper layout for free.
            "dev-code-seed",
            # Fixes a BA bug / hotfix (systematic debugging). Same reasoning:
            # not a story workflow, so it stays out of the tests'
            # DEV_WORKFLOW_SKILLS canon and has its own pins.
            "dev-fix-bug",
            # The Dev-repo SA agent: answers one technical question with
            # evidence, dispatched by dev-design/dev-plan or run as /dev-sa.
            # Not a phase of the ticket workflow, so it stays out of the
            # tests' DEV_WORKFLOW_SKILLS canon and has its own pins.
            "dev-sa",
        )
        for path, resource in (
            (f".claude/skills/{skill}/SKILL.md", f"claude-skill-{skill}.md"),
            (f".claude/commands/{skill}.md", f"claude-command-{skill}.md"),
            (f".github/prompts/{skill}.prompt.md", f"copilot-{skill}.prompt.md"),
            (f".cursor/commands/{skill}.md", f"cursor-{skill}.md"),
        )
    },
    # The twelve wrapper rows the seed flow (and later, ongoing amends) needs
    # from the existing authoring skills — paths copied verbatim from
    # COMMON_TEMPLATES so both maps resolve to the exact same package
    # resources. `kb-publish` genuinely has NO `.claude/commands/` resource in
    # the package (see COMMON_TEMPLATES above) — this map must not invent one.
    ".claude/skills/kb-summarize/SKILL.md": "claude-skill-kb-summarize.md",
    ".claude/commands/kb-summarize.md": "claude-command-kb-summarize.md",
    ".github/instructions/kb-summarize.instructions.md": "copilot-kb-summarize.instructions.md",
    ".cursor/commands/kb-summarize.md": "cursor-kb-summarize.md",
    ".cursor/rules/kb-summarize.mdc": "cursor-kb-summarize.mdc",
    ".claude/skills/kb-approve/SKILL.md": "claude-skill-kb-approve.md",
    ".claude/commands/kb-approve.md": "claude-command-kb-approve.md",
    ".github/prompts/kb-approve.prompt.md": "copilot-kb-approve.prompt.md",
    ".cursor/commands/kb-approve.md": "cursor-kb-approve.md",
    ".claude/skills/kb-publish/SKILL.md": "claude-skill-kb-publish.md",
    ".github/prompts/kb-publish.prompt.md": "copilot-kb-publish.prompt.md",
    ".cursor/commands/kb-publish.md": "cursor-kb-publish.md",
}

# Workflow files `kb init` scaffolds, by file name, across every kind. Their
# `run:` steps are strata's own (`kb build`, `kb pr lint …`), never the
# repo's build/lint/test, so `kb code-ingest`'s CI command reader skips them.
# Derived from the template maps so a new scaffolded workflow is covered
# the moment it is added to one.
SCAFFOLDED_WORKFLOW_NAMES: frozenset[str] = frozenset(
    rel.removeprefix(".github/workflows/")
    for templates in (
        COMMON_TEMPLATES,
        HUB_TEMPLATES,
        CHILD_TEMPLATES,
        BA_TEMPLATES,
        DEV_TEMPLATES,
    )
    for rel in templates
    if rel.startswith(".github/workflows/")
)

# User data — never refreshed by default; only overwritten with --force.
# `.claude/settings.json` joins the set because a dev's own hooks, permissions
# and model settings live there: initcmd overwrites anything outside this set
# (see the write branch below), which would silently delete their config on the
# next `kb init`. The cost of protecting it is that a repo scaffolded before
# the usage hook existed never gains it automatically — QUICKSTART carries the
# snippet to paste, which is the cheaper failure.
#
# `.gitignore` is NOT in this set — it gets its own merge-only handling
# (`_apply_gitignore`, below) instead of the generic skip-unless-force rule.
# A hub's own ignore rules (`.env`, credentials, editor cruft) must survive
# `kb init --force` too, not just a routine re-init — `--force` exists to
# refresh protected *scaffold* data (index.yaml, config.yaml), never to
# un-ignore a bearer token that `kb docker-setup` already wrote to `.env`.
PROTECTED_FILES: frozenset[str] = frozenset(
    {".kb/index.yaml", ".kb/config.yaml", ".claude/settings.json"}
)

_KB_WORK_LINE = ".kb-work/"


def _apply_gitignore(dest: Path, template_text: str, report: InitReport) -> None:
    """Merge-only, under EVERY mode — including `--force`.

    A hub's `.gitignore` may carry secret-exclusion rules (`.env`,
    credentials) a maintainer added after scaffolding; `kb docker-setup`
    itself appends `.env` there. `kb init --force` must never overwrite the
    whole file (that would silently un-ignore a bearer token). Mirrors
    `dockersetup.ensure_gitignored`'s append pattern: read lines, only
    append the missing entry, never rewrite existing content.
    """
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(template_text, encoding="utf-8", newline="\n")
        report.created.append(".gitignore")
        return
    try:
        lines = dest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        # A `.gitignore` this tool can't read — e.g. PowerShell 5.1's
        # `echo x > .gitignore` (UTF-16LE), mirroring doctor.check_hub —
        # is left untouched: an append would transcode content we could not
        # read, and an overwrite is exactly what R18 forbids. Report it and
        # let `kb doctor` surface the missing `.kb-work/` rule.
        report.skipped.append(".gitignore")
        report.notes.append(
            ".gitignore is not readable as UTF-8; left untouched. "
            f"Add `{_KB_WORK_LINE}` to it by hand."
        )
        return
    if any(line.strip() == _KB_WORK_LINE for line in lines):
        report.skipped.append(".gitignore")
        return
    lines.append(_KB_WORK_LINE)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    report.updated.append(".gitignore")


_CODE_DOC_LINE = ".kb/*-code/"
_PLAN_DOC_LINE = ".kb/*-plan/"
# A ba repo's index is generated by `kb plan-ingest`, so committing it makes
# the first `kb publish` refuse on a dirty `.kb/`. `kb ci-publish` walks the
# tree, so ignored files still upload.
_BA_INDEX_LINE = ".kb/index.yaml"


def _ensure_kb_doc_ignored(target: Path, line: str, report: InitReport) -> None:
    """Derived `.kb/` output is never committed: `-code` in dev repos,
    `-plan` and the index in ba repos. A glob for the doc, because repo_id is
    often unset at init time and `-code`/`-plan` are reserved suffixes.
    Append-only, like `_apply_gitignore`."""
    dest = target / ".gitignore"
    if not dest.exists():
        dest.write_text(line + "\n", encoding="utf-8", newline="\n")
        report.created.append(".gitignore")
        return
    try:
        lines = dest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        report.notes.append(
            ".gitignore is not readable as UTF-8; left untouched. "
            f"Add `{line}` to it by hand."
        )
        return
    if any(existing.strip() == line for existing in lines):
        return
    lines.append(line)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    report.updated.append(".gitignore")


_KIND_LINE = re.compile(r"^kind:", re.MULTILINE)
_LANGS_LINE = re.compile(r"^langs:", re.MULTILINE)

ASSET_MODES = ("none", "s3")
_ASSET_STORE_LINE = re.compile(r"^asset_store:", re.MULTILINE)

_ASSET_BLOCKS = {
    "none": "asset_store:\n  mode: none\n",
    "s3": (
        "asset_store:\n"
        "  # Object store for image assets. Fill bucket (and endpoint for\n"
        "  # MinIO/R2); credentials come from the environment (boto3 chain).\n"
        "  mode: s3\n"
        '  bucket: ""\n'
        '  region: ""\n'
        '  endpoint: ""\n'
        '  prefix: "assets/"\n'
    ),
}


def template_map(kind: str) -> dict[str, str]:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got '{kind}'")
    if kind == KIND_BA:
        return dict(BA_TEMPLATES)
    if kind == KIND_DEV:
        return dict(DEV_TEMPLATES)
    extra = HUB_TEMPLATES if kind == KIND_HUB else CHILD_TEMPLATES
    return {**COMMON_TEMPLATES, **extra}


def expected_files(kind: str) -> list[str]:
    return list(template_map(kind))


@dataclass
class InitReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _render(resource_name: str, text: str, repo_id: str) -> str:
    """Config templates carry {repo_id}; workflow and compose templates carry
    {version}, filled with the version of the CLI doing the scaffolding —
    read from the installed distribution's own metadata (the same value
    `kb --version` prints and the T2 release gate checks against
    pyproject.toml), not a hand-maintained constant that can drift from it.

    An unpinned `pip install strata-kb` inside a job that holds
    `id-token: write` means every child picks up whatever PyPI serves at run
    time, in a job able to write to the hub.

    Uses a plain substring replace (not str.format) so a future template
    containing literal `{`/`}` can't raise.
    """
    from importlib.metadata import version as _dist_version

    if resource_name.startswith("config-"):
        return text.replace("{repo_id}", repo_id)
    # Deliberately unguarded — unlike __init__.py's __version__, which falls
    # back to "0+unknown" for a source tree with no install. A scaffold must
    # never pin a placeholder version into a child's CI, so a missing
    # distribution here has to raise and fail `kb init` loudly, not render
    # `strata-kb==0+unknown` into a job that writes to the hub.
    return text.replace("{version}", _dist_version("strata-kb"))


def _record_kind(config_path: Path, kind: str) -> bool:
    """Append `kind:` to a pre-existing config.yaml that lacks it.

    Narrow exception to the protected-file skip: only ever ADDS the missing
    line, never rewrites user content (comments and values survive).
    """
    if not config_path.exists():
        return False
    text = config_path.read_text(encoding="utf-8")
    if _KIND_LINE.search(text):
        return False
    if text and not text.endswith("\n"):
        text += "\n"
    config_path.write_text(text + f"kind: {kind}\n", encoding="utf-8", newline="\n")
    return True


def record_langs(config_path: Path, langs: Sequence[str]) -> bool:
    """Append `langs: [a, b]` to a config.yaml that lacks the key — append-
    only, like _record_kind; an existing line is the operator's data."""
    if not langs or not config_path.exists():
        return False
    text = config_path.read_text(encoding="utf-8")
    if _LANGS_LINE.search(text):
        return False
    if text and not text.endswith("\n"):
        text += "\n"
    config_path.write_text(
        text + f"langs: [{', '.join(sorted(set(langs)))}]\n",
        encoding="utf-8",
        newline="\n",
    )
    return True


def _recorded_langs(config_path: Path, report: InitReport) -> list[str]:
    """Langs already on record in config.yaml, filtered to known ids.

    An operator can hand-edit `langs:` to a typo'd or since-renamed id
    (`langs: [Python]`, `langs: [nodejs]`); passing that straight into
    `forced` would 404 in `_template_text` or KeyError in `LANG_GLOBS`
    after the sorted loop has already half-written earlier packs. Drop
    unknown ids here instead and say so.
    """
    from strata_kb.config import load_config

    try:
        recorded = list(load_config(config_path.parent).langs)
    except Exception:  # noqa: BLE001 -- a broken config is doctor's job, not init's
        return []
    unknown = [lang for lang in recorded if lang not in conventions.LANG_IDS]
    if unknown:
        report.notes.append(
            f"unknown lang(s) {', '.join(unknown)} in .kb/config.yaml `langs:` "
            f"— ignored; valid ids: {', '.join(conventions.LANG_IDS)}"
        )
    return [lang for lang in recorded if lang in conventions.LANG_IDS]


def record_asset_store(config_path: Path, mode: str) -> str:
    """Append an asset_store block to config.yaml when absent.

    Append-only, like _record_kind: an existing block is the operator's
    data and is never rewritten. Returns "recorded" | "exists" | "no-config".
    """
    if mode not in ASSET_MODES:
        raise ValueError(f"assets mode must be one of {ASSET_MODES}, got '{mode}'")
    if not config_path.exists():
        return "no-config"
    text = config_path.read_text(encoding="utf-8")
    if _ASSET_STORE_LINE.search(text):
        return "exists"
    if text and not text.endswith("\n"):
        text += "\n"
    config_path.write_text(text + _ASSET_BLOCKS[mode], encoding="utf-8", newline="\n")
    return "recorded"


def _write_scaffold(dest: Path, rel: str, text: str, report: InitReport) -> None:
    if dest.exists():
        if dest.read_text(encoding="utf-8") == text:
            return
        dest.write_text(text, encoding="utf-8", newline="\n")
        report.updated.append(rel)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8", newline="\n")
    report.created.append(rel)


# The assistant's skills and commands, plus the review rubric the skills read:
# what `kb doctor` refreshes after it moved a repo to the hub's strata-kb. CI
# workflows, config, settings and `*.local.md` overrides are the repo's own and
# stay as they are.
AGENT_FILE_PREFIXES = (
    ".claude/skills/",
    ".claude/commands/",
    ".github/prompts/",
    ".cursor/commands/",
    "docs/pr-review-rubric.md",
)


def refresh_agent_files(target: Path, kind: str) -> InitReport:
    """`kb init` for `kind`, limited to AGENT_FILE_PREFIXES."""
    repo_id = target.resolve().name
    report = InitReport()
    for rel, resource_name in template_map(kind).items():
        if rel.startswith(AGENT_FILE_PREFIXES):
            text = _render(resource_name, read_template(resource_name), repo_id)
            _write_scaffold(target / rel, rel, text, report)
    return report


def init_repo(
    target: Path,
    kind: str,
    force: bool = False,
    assets: str | None = None,
    langs: Sequence[str] = (),
) -> InitReport:
    """Scaffold a KB repo as the given kind (hub | child).

    Default: create missing files and refresh scaffold templates whose content
    changed. Protected data (``.kb/index.yaml``, ``.kb/config.yaml``,
    ``.claude/settings.json``) is left alone unless ``force=True``. The root
    ``.gitignore`` is handled separately and is always merge-only — it is
    never wholesale-overwritten, even with ``force=True``.
    """
    templates = template_map(kind)
    repo_id = target.resolve().name
    report = InitReport()
    for rel, resource_name in templates.items():
        dest = target / rel
        text = _render(resource_name, read_template(resource_name), repo_id)
        if rel == ".gitignore":
            _apply_gitignore(dest, text, report)
            continue
        if dest.exists() and rel in PROTECTED_FILES and not force:
            report.skipped.append(rel)
            continue
        _write_scaffold(dest, rel, text, report)
    if _record_kind(target / ".kb" / "config.yaml", kind):
        if ".kb/config.yaml" in report.skipped:
            report.skipped.remove(".kb/config.yaml")
        report.updated.append(".kb/config.yaml (kind recorded)")
    if kind == KIND_BA:
        _ensure_kb_doc_ignored(target, _PLAN_DOC_LINE, report)
        _ensure_kb_doc_ignored(target, _BA_INDEX_LINE, report)
        scaffold_ba_local_overrides(target, report)
    if kind == KIND_DEV:
        _ensure_kb_doc_ignored(target, _CODE_DOC_LINE, report)
        scaffold_dev_local_overrides(target, report)
        done, conflicts = impltidy.tidy(target / "docs" / "impl")
        report.notes.extend(f"moved: {s} → {d}" for s, d in done)
        report.notes.extend(conflicts)
        cfg_path = target / ".kb" / "config.yaml"
        recorded = _recorded_langs(cfg_path, report)
        forced = sorted(set(langs) | set(recorded))
        scaffolded = conventions.scaffold_conventions(target, report, forced=forced)
        if scaffolded:
            conventions.ensure_claude_block(target, report)
        if langs:
            if record_langs(cfg_path, forced):
                report.updated.append(".kb/config.yaml (langs recorded)")
            elif recorded:
                # Mirrors record_asset_store's "exists" branch below: append-
                # only means --lang cannot change an already-recorded value.
                report.notes.append(
                    f"--lang ignored — .kb/config.yaml already has "
                    f"langs: [{', '.join(recorded)}]; hand-edit langs: there "
                    "to change it"
                )
    if assets is not None:
        outcome = record_asset_store(target / ".kb" / "config.yaml", assets)
        if outcome == "recorded":
            report.updated.append(".kb/config.yaml (asset_store recorded)")
        elif outcome == "exists":
            report.notes.append(
                "asset_store already configured in .kb/config.yaml — left unchanged"
            )
    return report
