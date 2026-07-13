from __future__ import annotations

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
}

HUB_TEMPLATES: dict[str, str] = {
    ".kb/config.yaml": "config-hub.yaml",
    "docker-compose.yml": "docker-compose-hub.yml",
    ".env.example": "env.example",
    "federation/README.md": "federation-README.md",
    ".mcp.json": "mcp-hub.json",
    "QUICKSTART.md": "QUICKSTART-hub.md",
}

# Filled in by the child-scaffold task; kept separate so hub and child can
# diverge artifact-by-artifact.
CHILD_TEMPLATES: dict[str, str] = {
    ".kb/config.yaml": "config-child.yaml",
    "docker-compose.yml": "docker-compose-child.yml",
    ".mcp.json": "mcp-child.json",
    "QUICKSTART.md": "QUICKSTART-child.md",
}

# User data — never refreshed by default; only overwritten with --force.
PROTECTED_FILES: frozenset[str] = frozenset({".kb/index.yaml", ".kb/config.yaml"})


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
    """Config templates carry a {repo_id} placeholder; everything else is static."""
    if resource_name.startswith("config-"):
        return text.format(repo_id=repo_id)
    return text


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
    return report
