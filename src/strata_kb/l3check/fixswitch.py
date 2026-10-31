"""fixswitch — the `l3_fix:` block in `.kb/config.yaml`: the AI structure fix switch.

Turning it on also keeps `.kb-work/` (drafts, page images) out of git.
"""

from __future__ import annotations

from pathlib import Path

from strata_kb import gitio
from strata_kb.config import CONFIG_NAME, load_config, set_block_enabled

WORK_DIR_IGNORE = ".kb-work/"


def is_on(kb_dir: Path) -> bool:
    return load_config(kb_dir).l3_fix.enabled


def turn_on(kb_dir: Path) -> list[str]:
    """Set the flag and gitignore `.kb-work/`. Returns one echo line per action."""
    set_block_enabled(kb_dir / CONFIG_NAME, "l3_fix", True)
    lines = ["l3_fix: on"]
    try:
        root = gitio.git_root(kb_dir.resolve())
    except (gitio.GitError, OSError):
        root = kb_dir.parent
    gitignore = root / ".gitignore"
    text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if not {line.strip() for line in text.splitlines()} & {
        WORK_DIR_IGNORE,
        WORK_DIR_IGNORE.rstrip("/"),
    }:
        sep = "" if not text or text.endswith("\n") else "\n"
        gitignore.write_text(
            f"{text}{sep}{WORK_DIR_IGNORE}\n", encoding="utf-8", newline="\n"
        )
        lines.append(f"added {WORK_DIR_IGNORE} to {gitignore}")
    return lines


def turn_off(kb_dir: Path) -> None:
    set_block_enabled(kb_dir / CONFIG_NAME, "l3_fix", False)
