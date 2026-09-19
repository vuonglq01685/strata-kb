import json

import pytest

from strata_kb import llm
from strata_kb.models import LLMConfig
from strata_kb.summarize import PendingSection, build_section_prompt
from tests.cli_stub import echo_after_stdin, echo_stdin_length, write_cli_stub


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
    exe = write_cli_stub(tmp_path, "claude", echo_after_stdin(envelope))
    runner = llm.Runner("claude", str(exe), "sonnet-5", "high", 30)
    assert json.loads(runner.run("prompt")) == {"l2_summary": "x", "l1_summary": "y"}


def test_copilot_run_pipes_prompt_on_stdin(tmp_path):
    exe = write_cli_stub(tmp_path, "copilot", echo_stdin_length())
    runner = llm.Runner("copilot", str(exe), "gpt-5", "high", 30)
    prompt = "line one\nline two %PATH% & | > ^ !x!"
    n, tail = runner.run(prompt).split("|", 1)
    assert int(n) == len(prompt) and tail == prompt[-30:]


@pytest.mark.parametrize("name", ["claude", "copilot"])
def test_full_section_prompt_arrives_intact(tmp_path, name):
    """B-1: a real multi-line ~3.5 kB prompt with shell metacharacters must
    reach the CLI byte for byte — through the .cmd shim on Windows."""
    body = ("## 5.7 Route Type\n\n" + "Route type codes & their meaning | see %PATH% ^ !x! > 0.\n" * 60)
    prompt = build_section_prompt(PendingSection("d", "5.7", "Route Type", "f", body))
    assert "\n" in prompt and len(prompt) > 3000
    if name == "claude":
        stub = (
            "import sys, json\n"
            "data = sys.stdin.read()\n"
            "print(json.dumps({'type': 'result', 'result': str(len(data)) + '|' + data[-30:]}))\n"
        )
    else:
        stub = echo_stdin_length()
    exe = write_cli_stub(tmp_path, name, stub)
    runner = llm.Runner(name, str(exe), "m", "high", 30)
    n, tail = runner.run(prompt).split("|", 1)
    assert int(n) == len(prompt) and tail == prompt[-30:]


def test_run_never_puts_the_prompt_in_argv(tmp_path, monkeypatch):
    seen = {}
    def fake_run(cmd, **kw):
        seen["cmd"], seen["input"] = cmd, kw.get("input")

        class P:
            returncode, stdout, stderr = 0, '{"type": "result", "result": "ok"}', ""

        return P()
    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    for name in ("claude", "copilot"):
        llm.Runner(name, "x", "m", "high", 1).run("the prompt")
        assert "the prompt" not in seen["cmd"] and seen["input"] == "the prompt"


@pytest.mark.parametrize(("name", "expected_cmd"), [
    ("claude", ["x", "-p", "--model", "m", "--output-format", "json"]),
    # copilot: no -p/--prompt — a bare -p would swallow --model as the
    # prompt value and ignore stdin (controller ruling R7; see Evidence).
    ("copilot", ["x", "--model", "m", "-s"]),
])
def test_run_argv_shape_per_runner(monkeypatch, name, expected_cmd):
    seen = {}
    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw

        class P:
            returncode, stdout, stderr = 0, '{"type": "result", "result": "ok"}', ""

        return P()
    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    llm.Runner(name, "x", "m", "high", 1).run("the prompt")
    assert seen["cmd"] == expected_cmd
    assert seen["kw"]["encoding"] == "utf-8"
    assert seen["kw"]["text"] is True
    assert seen["kw"]["input"] == "the prompt"


@pytest.mark.parametrize("envelope", [
    {"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "API Error: 500"},
    {"type": "result", "subtype": "error_max_turns", "is_error": True, "result": ""},
    {"type": "result", "subtype": "success"},           # no result key at all
])
def test_claude_envelope_errors_raise(tmp_path, envelope):
    exe = write_cli_stub(tmp_path, "claude", echo_after_stdin(json.dumps(envelope)))
    runner = llm.Runner("claude", str(exe), "sonnet-5", "high", 30)
    with pytest.raises(llm.RunnerError) as ei:
        runner.run("prompt")
    if envelope.get("result"):
        assert "API Error: 500" in str(ei.value)


def test_run_raises_on_nonzero_exit(tmp_path):
    exe = write_cli_stub(
        tmp_path, "claude", "import sys\nsys.stdin.read()\nsys.exit(3)\n"
    )
    runner = llm.Runner("claude", str(exe), "sonnet-5", "high", 30)
    with pytest.raises(llm.RunnerError):
        runner.run("prompt")


def test_run_raises_runner_error_when_prompt_lands_in_argv():
    """A5: forcing config.model to equal the prompt reproduces the
    argv-injection shape without needing a real CLI stub -- the guard
    must raise RunnerError (not AssertionError, which -O strips) before
    any subprocess is spawned."""
    runner = llm.Runner("claude", "x", "the prompt", "high", 1)
    with pytest.raises(llm.RunnerError, match="stdin"):
        runner.run("the prompt")


def test_run_raises_on_timeout(tmp_path):
    exe = write_cli_stub(
        tmp_path, "claude",
        "import sys, time\nsys.stdin.read()\ntime.sleep(5)\n",
    )
    runner = llm.Runner("claude", str(exe), "sonnet-5", "high", 1)
    with pytest.raises(llm.RunnerError):
        runner.run("prompt")
