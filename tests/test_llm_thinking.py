"""2026-10-10 review §6.2 F12: effort=high sent MAX_THINKING_TOKENS=31999 for
every section, a two-line one included. The budget now scales with the
prompt, clamped."""

from __future__ import annotations

import subprocess

import pytest

from strata_kb import llm


@pytest.mark.parametrize(
    ("chars", "budget"),
    [
        (0, 4000),
        (3_000, 4000),
        (8_000, 4000),
        (20_000, 10_000),
        (63_998, 31_999),
        (500_000, 31_999),
    ],
)
def test_thinking_budget_scales_and_clamps(chars, budget):
    assert llm.thinking_budget("x" * chars) == budget


def _env_of_run(monkeypatch, runner, prompt):
    seen = {}

    def fake_run(cmd, **kw):
        seen["env"] = kw.get("env")
        return subprocess.CompletedProcess(
            cmd, 0, '{"type":"result","result":"ok"}', ""
        )

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    runner.run(prompt)
    return seen["env"]


def test_claude_high_effort_sends_the_scaled_budget(monkeypatch):
    runner = llm.Runner("claude", "claude", "sonnet-5", "high", 30)
    env = _env_of_run(monkeypatch, runner, "p" * 30_000)
    assert env["MAX_THINKING_TOKENS"] == "15000"


@pytest.mark.parametrize(
    ("name", "effort"), [("claude", "medium"), ("copilot", "high")]
)
def test_no_budget_unless_claude_at_high_effort(monkeypatch, name, effort):
    runner = llm.Runner(name, name, "m", effort, 30)
    assert _env_of_run(monkeypatch, runner, "p" * 30_000) is None
