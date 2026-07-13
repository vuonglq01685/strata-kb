from __future__ import annotations

import sys


def force_utf8_streams() -> None:
    """Reconfigure stdin/stdout/stderr to UTF-8.

    Windows consoles are UTF-8-capable since PEP 528, but pipes/redirects
    still default to the locale codepage (cp1252) — printing '§' or reading
    Vietnamese input then crashes or mojibakes. Guarded: test doubles and
    exotic streams may lack .reconfigure().
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None) or ""
        if encoding.lower().replace("-", "") != "utf8" and hasattr(
            stream, "reconfigure"
        ):
            stream.reconfigure(encoding="utf-8")
