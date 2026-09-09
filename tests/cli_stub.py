"""Portable fake CLI executables — '#!/bin/sh' stubs don't run on Windows.

The stub is a two-part pair: <name>_impl.py (the behavior, plain Python) plus
a thin OS wrapper — `<name>` sh script on POSIX, `<name>.cmd` on Windows
(shutil.which resolves .cmd via PATHEXT)."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


_FORCE_UTF8_STDIO = (
    "import sys\n"
    "sys.stdin.reconfigure(encoding='utf-8')\n"
    "sys.stdout.reconfigure(encoding='utf-8')\n"
)


def write_cli_stub(bindir: Path, name: str, python_body: str) -> Path:
    """Write the stub. Stdio is forced to UTF-8 regardless of the host's
    default locale codec (e.g. cp1252 on Windows), so byte-for-byte prompt
    round-tripping doesn't depend on the box's console codepage."""
    bindir.mkdir(parents=True, exist_ok=True)
    impl = bindir / f"{name}_impl.py"
    impl.write_text(_FORCE_UTF8_STDIO + python_body, encoding="utf-8", newline="\n")
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
    """Print payload after consuming stdin (every runner now pipes the prompt)."""
    return echo_after_stdin(payload)


def echo_stdin_length() -> str:
    """Print '<n chars>|<last 30 chars>' of what arrived on stdin."""
    return (
        "import sys\n"
        "data = sys.stdin.read()\n"
        "sys.stdout.write(str(len(data)) + '|' + data[-30:] + '\\n')\n"
    )
