from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

KIND_HUB = "hub"
KIND_CHILD = "child"
KIND_BA = "ba"
KIND_DEV = "dev"
KINDS = (KIND_HUB, KIND_CHILD, KIND_BA, KIND_DEV)

# target relative path -> template resource name under templates/init/
COMMON_TEMPLATES: dict[str, str] = {
    ".kb/index.yaml": "index.yaml",
    "source/.gitignore": "source-gitignore.txt",
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

HUB_TEMPLATES: dict[str, str] = {
    ".kb/config.yaml": "config-hub.yaml",
    "docker-compose.yml": "docker-compose-hub.yml",
    ".env.example": "env.example",
    "federation/README.md": "federation-README.md",
    ".mcp.json": "mcp-hub.json",
    "QUICKSTART.md": "QUICKSTART-hub.md",
    ".cursor/mcp.json": "mcp-hub.json",
}

# Filled in by the child-scaffold task; kept separate so hub and child can
# diverge artifact-by-artifact.
CHILD_TEMPLATES: dict[str, str] = {
    ".kb/config.yaml": "config-child.yaml",
    "docker-compose.yml": "docker-compose-child.yml",
    ".mcp.json": "mcp-child.json",
    "QUICKSTART.md": "QUICKSTART-child.md",
    ".cursor/mcp.json": "cursor-mcp-child.json",
}

# Kind `ba` — requirements repo. It consumes the shared KB (via the
# ba-ticket-author skill + MCP) and versions tickets; it authors no KB
# documents itself, so it carries none of the ingest/summarize/publish
# machinery. Deliberately NOT merged with COMMON_TEMPLATES (spec §8): a ba
# repo gets exactly this set, nothing from the hub/child authoring stack.
BA_TEMPLATES: dict[str, str] = {
    ".kb/config.yaml": "config-ba.yaml",
    ".mcp.json": "mcp-child.json",
    ".claude/settings.json": "claude-settings-usage.json",
    ".cursor/mcp.json": "cursor-mcp-child.json",
    ".claude/skills/ba-ticket-author/SKILL.md": "claude-skill-ba-ticket-author.md",
    ".claude/commands/ba-ticket-author.md": "claude-command-ba-ticket-author.md",
    ".github/prompts/ba-ticket-author.prompt.md": "copilot-ba-ticket-author.prompt.md",
    ".cursor/commands/ba-ticket-author.md": "cursor-ba-ticket-author.md",
    ".claude/skills/ba-mission-plan/SKILL.md": "claude-skill-ba-mission-plan.md",
    ".claude/commands/ba-mission-plan.md": "claude-command-ba-mission-plan.md",
    ".github/prompts/ba-mission-plan.prompt.md": "copilot-ba-mission-plan.prompt.md",
    ".cursor/commands/ba-mission-plan.md": "cursor-ba-mission-plan.md",
    "docs/tickets/TEMPLATE.md": "ticket-template.md",
    "docs/missions/TEMPLATE.md": "mission-template.md",
    "docs/ac-quality.md": "ac-quality.md",
    "docs/review-rubric.md": "review-rubric.md",
    "tickets/.gitkeep": "gitkeep.txt",
    "missions/.gitkeep": "gitkeep.txt",
    ".github/workflows/kb-ticket-lint.yml": "kb-ticket-lint.yml",
    "QUICKSTART-BA.md": "QUICKSTART-ba.md",
}

# Kind `dev` — product code repo. It consumes the shared KB while implementing
# BA tickets and publishes knowledge about its OWN source code. Like BA_TEMPLATES
# this is deliberately NOT merged with COMMON_TEMPLATES (spec §4): a dev repo
# never ingests outside documents, so it carries none of the ingest/docker stack.
DEV_TEMPLATES: dict[str, str] = {
    ".kb/config.yaml": "config-dev.yaml",
    ".kb/index.yaml": "index.yaml",
    ".mcp.json": "mcp-child.json",
    ".claude/settings.json": "claude-settings-usage.json",
    ".cursor/mcp.json": "cursor-mcp-child.json",
    "docs/impl/.gitkeep": "gitkeep.txt",
    "docs/impl/.gitignore": "impl-gitignore.txt",
    "QUICKSTART-DEV.md": "QUICKSTART-dev.md",
    ".github/workflows/kb-code.yml": "kb-code.yml",
    **{
        path: resource
        for skill in (
            "dev-implement-ticket",
            "dev-design",
            "dev-plan",
            "dev-execute",
            "dev-handover",
            # Stage C: the one-time bootstrap skill. Added to this tuple
            # (not to the tests' DEV_WORKFLOW_SKILLS lists — it implements
            # no ticket, so the ticket-shaped SHARED-* canon doesn't apply
            # to it) so it gets the same four-way wrapper layout for free.
            "dev-code-seed",
        )
        for path, resource in (
            (f".claude/skills/{skill}/SKILL.md", f"claude-skill-{skill}.md"),
            (f".claude/commands/{skill}.md", f"claude-command-{skill}.md"),
            (f".github/prompts/{skill}.prompt.md", f"copilot-{skill}.prompt.md"),
            (f".cursor/commands/{skill}.md", f"cursor-{skill}.md"),
        )
    },
    # Stage C: the twelve wrapper rows the seed flow (and later, ongoing
    # amends) needs from the existing authoring skills — paths copied
    # verbatim from COMMON_TEMPLATES so both maps resolve to the exact same
    # package resources. `kb-publish` genuinely has NO `.claude/commands/`
    # resource in the package (see COMMON_TEMPLATES above) — this map must
    # not invent one.
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

# User data — never refreshed by default; only overwritten with --force.
# `.claude/settings.json` joins the set because a dev's own hooks, permissions
# and model settings live there: initcmd overwrites anything outside this set
# (see the write branch below), which would silently delete their config on the
# next `kb init`. The cost of protecting it is that a repo scaffolded before
# the usage hook existed never gains it automatically — QUICKSTART carries the
# snippet to paste, which is the cheaper failure.
PROTECTED_FILES: frozenset[str] = frozenset(
    {".kb/index.yaml", ".kb/config.yaml", ".claude/settings.json"}
)

_KIND_LINE = re.compile(r"^kind:", re.MULTILINE)

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
    """Config templates carry a {repo_id} placeholder; everything else is static.

    Uses a plain substring replace (not str.format) so a future config
    template containing literal `{`/`}` can't raise.
    """
    if resource_name.startswith("config-"):
        return text.replace("{repo_id}", repo_id)
    return text


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


def init_repo(
    target: Path, kind: str, force: bool = False, assets: str | None = None
) -> InitReport:
    """Scaffold a KB repo as the given kind (hub | child).

    Default: create missing files and refresh scaffold templates whose content
    changed. Protected data (``.kb/index.yaml``, ``.kb/config.yaml``,
    ``.claude/settings.json``) is left alone unless ``force=True``.
    """
    templates = template_map(kind)
    base = resources.files("center_kb").joinpath("templates/init")
    repo_id = target.resolve().name
    report = InitReport()
    for rel, resource_name in templates.items():
        dest = target / rel
        text = _render(
            resource_name,
            base.joinpath(resource_name).read_text(encoding="utf-8"),
            repo_id,
        )
        if dest.exists():
            if rel in PROTECTED_FILES and not force:
                report.skipped.append(rel)
                continue
            if dest.read_text(encoding="utf-8") == text:
                continue
            dest.write_text(text, encoding="utf-8", newline="\n")
            report.updated.append(rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8", newline="\n")
        report.created.append(rel)
    if _record_kind(target / ".kb" / "config.yaml", kind):
        if ".kb/config.yaml" in report.skipped:
            report.skipped.remove(".kb/config.yaml")
        report.updated.append(".kb/config.yaml (kind recorded)")
    if assets is not None:
        outcome = record_asset_store(target / ".kb" / "config.yaml", assets)
        if outcome == "recorded":
            report.updated.append(".kb/config.yaml (asset_store recorded)")
        elif outcome == "exists":
            report.notes.append(
                "asset_store already configured in .kb/config.yaml — left unchanged"
            )
    return report
