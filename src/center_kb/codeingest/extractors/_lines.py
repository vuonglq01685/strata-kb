"""Shell-text line helper shared by the commands and services readers.

A CI `run: |` block, a tox `commands =` value, a shell script and a
Dockerfile all use `\\` line continuation; splitting such text per line
shipped fragments like `--tag ghcr.io/x:latest \\` as commands (reviewer
G-2). Joining lives here, once, rather than per reader.
"""
from __future__ import annotations


def join_continuations(text: str) -> list[str]:
    """Logical lines of `text`: a line ending in `\\` is joined to the
    next with one space; blank lines and lines whose first non-blank
    character is `#` are dropped. Every line is stripped."""
    joined: list[str] = []
    pending = ""
    for raw in text.splitlines():
        line = raw.strip()
        if pending:
            line = f"{pending} {line}".strip()
            pending = ""
        if line.endswith("\\"):
            pending = line[:-1].rstrip()
            continue
        if not line or line.startswith("#"):
            continue
        joined.append(line)
    if pending:
        joined.append(pending)
    return joined
