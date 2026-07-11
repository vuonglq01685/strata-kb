import json
import stat
from pathlib import Path

import pytest

from center_kb import llm
from center_kb.models import LLMConfig


def make_stub(tmp_path: Path, name: str, body: str) -> str:
    """Create an executable shell script standing in for a real CLI."""
    script = tmp_path / name
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


# --- detect_runner -----------------------------------------------------------

def test_detect_prefers_claude_then_copilot(monkeypatch):
    monkeypatch.setattr(
        llm.shutil, "which",
        lambda n: f"/bin/{n}" if n in ("claude", "copilot") else None,
    )
    runner = llm.detect_runner(None, LLMConfig())
    assert runner is not None and runner.name == "claude"


def test_detect_falls_back_to_copilot(monkeypatch):
    monkeypatch.setattr(
        llm.shutil, "which", lambda n: "/bin/copilot" if n == "copilot" else None
    )
    runner = llm.detect_runner(None, LLMConfig())
    assert runner is not None and runner.name == "copilot"


def test_detect_returns_none_when_nothing_installed(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda n: None)
    assert llm.detect_runner(None, LLMConfig()) is None


def test_cli_choice_overrides_config(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda n: f"/bin/{n}")
    runner = llm.detect_runner("copilot", LLMConfig(runner="claude"))
    assert runner.name == "copilot"


def test_config_runner_none_disables():
    assert llm.detect_runner(None, LLMConfig(runner="none")) is None


def test_runner_carries_config_values(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda n: f"/bin/{n}")
    cfg = LLMConfig(model="sonnet-5", effort="high", timeout=42)
    runner = llm.detect_runner("claude", cfg)
    assert (runner.model, runner.effort, runner.timeout) == ("sonnet-5", "high", 42)


# --- Runner.run --------------------------------------------------------------

def test_claude_run_unwraps_json_envelope(tmp_path):
    inner = json.dumps({"l2_summary": "x", "l1_summary": "y"})
    envelope = json.dumps({"type": "result", "result": inner})
    exe = make_stub(tmp_path, "claude", f"cat > /dev/null\necho '{envelope}'")
    runner = llm.Runner("claude", exe, "sonnet-5", "high", 30)
    assert json.loads(runner.run("prompt")) == {"l2_summary": "x", "l1_summary": "y"}


def test_copilot_run_returns_plain_stdout(tmp_path):
    exe = make_stub(tmp_path, "copilot", 'echo \'{"l2_summary": "a", "l1_summary": "b"}\'')
    runner = llm.Runner("copilot", exe, "gpt-5", "high", 30)
    assert '"l2_summary"' in runner.run("prompt")


def test_run_raises_on_nonzero_exit(tmp_path):
    exe = make_stub(tmp_path, "claude", "cat > /dev/null\nexit 3")
    runner = llm.Runner("claude", exe, "sonnet-5", "high", 30)
    with pytest.raises(llm.RunnerError):
        runner.run("prompt")


def test_run_raises_on_timeout(tmp_path):
    exe = make_stub(tmp_path, "claude", "cat > /dev/null\nsleep 5")
    runner = llm.Runner("claude", exe, "sonnet-5", "high", 1)
    with pytest.raises(llm.RunnerError):
        runner.run("prompt")
