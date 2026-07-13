"""Portable fake CLI executables — '#!/bin/sh' stubs don't run on Windows.

The stub is a two-part pair: <name>_impl.py (the behavior, plain Python) plus
a thin OS wrapper — `<name>` sh script on POSIX, `<name>.cmd` on Windows
(shutil.which resolves .cmd via PATHEXT)."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


def write_cli_stub(bindir: Path, name: str, python_body: str) -> Path:
    bindir.mkdir(parents=True, exist_ok=True)
    impl = bindir / f"{name}_impl.py"
    impl.write_text(python_body, encoding="utf-8", newline="\n")
    if os.name == "nt":
        stub = bindir / f"{name}.cmd"
        stub.write_text(f'@"{sys.executable}" "{impl}" %*\n', encoding="utf-8")
        return stub
    stub = bindir / name
    stub.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{impl}" "$@"\n',
        encoding="utf-8", newline="\n",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return stub


def echo_after_stdin(payload: str) -> str:
    """Consume stdin (claude -p pipes the prompt), then print payload."""
    return f"import sys\nsys.stdin.read()\nsys.stdout.write({payload!r} + '\\n')\n"


def echo(payload: str) -> str:
    """Print payload without touching stdin (copilot takes prompt as argv)."""
    return f"import sys\nsys.stdout.write({payload!r} + '\\n')\n"
