from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

KIND_HUB = "hub"
KIND_CHILD = "child"
KINDS = (KIND_HUB, KIND_CHILD)

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
}

HUB_TEMPLATES: dict[str, str] = {
    ".kb/config.yaml": "config-hub.yaml",
    "docker-compose.yml": "docker-compose-hub.yml",
    ".env.example": "env.example",
    "federation/README.md": "federation-README.md",
    ".mcp.json": "mcp-hub.json",
    "QUICKSTART.md": "QUICKSTART-hub.md",
    ".claude/skills/kb-docker-setup/SKILL.md": "claude-skill-kb-docker-setup.md",
    ".claude/commands/kb-docker-setup.md": "claude-command-kb-docker-setup.md",
    ".github/prompts/kb-docker-setup.prompt.md": "copilot-kb-docker-setup.prompt.md",
    ".cursor/commands/kb-docker-setup.md": "cursor-kb-docker-setup.md",
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

# User data — never refreshed by default; only overwritten with --force.
PROTECTED_FILES: frozenset[str] = frozenset({".kb/index.yaml", ".kb/config.yaml"})

_KIND_LINE = re.compile(r"^kind:", re.MULTILINE)


def template_map(kind: str) -> dict[str, str]:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got '{kind}'")
    extra = HUB_TEMPLATES if kind == KIND_HUB else CHILD_TEMPLATES
    return {**COMMON_TEMPLATES, **extra}


def expected_files(kind: str) -> list[str]:
    return list(template_map(kind))


@dataclass
class InitReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


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
    config_path.write_text(text + f"kind: {kind}\n", encoding="utf-8")
    return True


def init_repo(target: Path, kind: str, force: bool = False) -> InitReport:
    """Scaffold a KB repo as the given kind (hub | child).

    Default: create missing files and refresh scaffold templates whose content
    changed. Protected data (``.kb/index.yaml``, ``.kb/config.yaml``) is left
    alone unless ``force=True``.
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
            dest.write_text(text, encoding="utf-8")
            report.updated.append(rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        report.created.append(rel)
    if _record_kind(target / ".kb" / "config.yaml", kind):
        if ".kb/config.yaml" in report.skipped:
            report.skipped.remove(".kb/config.yaml")
        report.updated.append(".kb/config.yaml (kind recorded)")
    return report
