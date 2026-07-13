"""Windows pipes/redirects default to cp1252 — force UTF-8 at the entrypoints
(spec 2026-07-14-windows-support R2/R3)."""
import os
import subprocess
import sys


def _run_py(code: str, input_bytes: bytes = b"") -> subprocess.CompletedProcess[bytes]:
    # PYTHONIOENCODING=cp1252 simulates a Windows pipe on any OS.
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    return subprocess.run(
        [sys.executable, "-c", code], input=input_bytes,
        capture_output=True, env=env,
    )


def test_cli_import_forces_utf8_stdout():
    proc = _run_py("from center_kb import cli\nprint('§ tiếng Việt')")
    assert proc.returncode == 0, proc.stderr
    assert "§ tiếng Việt".encode("utf-8") in proc.stdout


def test_cli_import_forces_utf8_stdin():
    # Without the fix, UTF-8 bytes on stdin decode as cp1252 → mojibake.
    proc = _run_py(
        "from center_kb import cli\nimport sys\nsys.stdout.write(sys.stdin.read())",
        input_bytes="§ tiếng Việt".encode("utf-8"),
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.decode("utf-8") == "§ tiếng Việt"


class _FakeStream:
    def __init__(self, encoding: str) -> None:
        self.encoding = encoding
        self.calls: list[dict] = []

    def reconfigure(self, **kwargs) -> None:
        self.calls.append(kwargs)


def test_force_utf8_streams_skips_utf8_and_reconfigures_legacy(monkeypatch):
    from center_kb import utf8io

    legacy, modern = _FakeStream("cp1252"), _FakeStream("utf-8")
    monkeypatch.setattr(utf8io.sys, "stdin", legacy)
    monkeypatch.setattr(utf8io.sys, "stdout", modern)
    monkeypatch.setattr(utf8io.sys, "stderr", _FakeStream("UTF-8"))
    utf8io.force_utf8_streams()
    assert legacy.calls == [{"encoding": "utf-8"}]
    assert modern.calls == []


def test_force_utf8_streams_tolerates_streams_without_reconfigure(monkeypatch):
    from center_kb import utf8io

    monkeypatch.setattr(utf8io.sys, "stdin", object())  # e.g. test doubles
    utf8io.force_utf8_streams()  # must not raise
