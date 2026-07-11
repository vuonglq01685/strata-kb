from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

# target relative path -> template resource name under templates/init/
TEMPLATE_MAP: dict[str, str] = {
    ".kb/index.yaml": "index.yaml",
    "federation/README.md": "federation-README.md",
    "source/.gitignore": "source-gitignore.txt",
    ".mcp.json": "mcp.json",
    ".github/workflows/kb-review.yml": "kb-review.yml",
    "docker-compose.yml": "docker-compose.yml",
    ".env.example": "env.example",
    "QUICKSTART.md": "QUICKSTART.md",
    ".claude/skills/kb-summarize/SKILL.md": "claude-skill-kb-summarize.md",
    ".github/instructions/kb-summarize.instructions.md": "copilot-kb-summarize.instructions.md",
    ".claude/skills/kb-ingest/SKILL.md": "claude-skill-kb-ingest.md",
    ".github/prompts/kb-ingest.prompt.md": "copilot-kb-ingest.prompt.md",
    ".claude/skills/kb-publish/SKILL.md": "claude-skill-kb-publish.md",
    ".github/prompts/kb-publish.prompt.md": "copilot-kb-publish.prompt.md",
}
EXPECTED_FILES = list(TEMPLATE_MAP)


@dataclass
class InitReport:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def init_repo(target: Path, force: bool = False) -> InitReport:
    """Scaffold a KB repo. Never overwrites existing files unless force=True."""
    base = resources.files("center_kb").joinpath("templates/init")
    report = InitReport()
    for rel, resource_name in TEMPLATE_MAP.items():
        dest = target / rel
        if dest.exists() and not force:
            report.skipped.append(rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = base.joinpath(resource_name).read_text(encoding="utf-8")
        dest.write_text(text, encoding="utf-8")
        report.created.append(rel)
    return report
