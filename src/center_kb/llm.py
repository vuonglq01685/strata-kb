from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass

from center_kb.models import LLMConfig

# `claude -p` has no public effort flag; a large thinking budget is the
# closest supported knob for effort=high (spec §6 — best-effort).
HIGH_EFFORT_THINKING_TOKENS = "31999"


class RunnerError(Exception):
    """LLM CLI call failed: non-zero exit, timeout, or unusable output."""


@dataclass(frozen=True)
class Runner:
    name: str  # "claude" | "copilot"
    executable: str
    model: str
    effort: str
    timeout: int

    def run(self, prompt: str) -> str:
        """One headless call; returns the model's reply text."""
        if self.name == "claude":
            # prompt via stdin: avoids ARG_MAX limits on long L3 bodies
            cmd = [self.executable, "-p", "--model", self.model,
                   "--output-format", "json"]
            stdin: str | None = prompt
        else:
            # copilot CLI takes the prompt as an argument, not stdin
            cmd = [self.executable, "-p", prompt, "--model", self.model]
            stdin = None
        env = None
        if self.name == "claude" and self.effort == "high":
            env = os.environ | {"MAX_THINKING_TOKENS": HIGH_EFFORT_THINKING_TOKENS}
        try:
            proc = subprocess.run(
                cmd, input=stdin, capture_output=True, text=True,
                timeout=self.timeout, env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise RunnerError(f"{self.name}: timed out after {self.timeout}s") from exc
        if proc.returncode != 0:
            raise RunnerError(
                f"{self.name}: exit {proc.returncode}: {proc.stderr.strip()[:500]}"
            )
        return _extract_reply(self.name, proc.stdout)


def _extract_reply(name: str, stdout: str) -> str:
    if name != "claude":
        return stdout.strip()
    # claude --output-format json wraps the reply: {"type":"result","result":"…"}
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout.strip()
    if isinstance(envelope, dict) and isinstance(envelope.get("result"), str):
        return envelope["result"].strip()
    return stdout.strip()


def detect_runner(cli_choice: str | None, config: LLMConfig) -> Runner | None:
    """Resolve the runner: CLI flag > index.yaml config > auto-detect.

    Returns None when disabled ("none") or no supported CLI is installed.
    """
    choice = cli_choice or config.runner
    if choice == "none":
        return None
    candidates = [choice] if choice in ("claude", "copilot") else ["claude", "copilot"]
    for name in candidates:
        path = shutil.which(name)
        if path:
            return Runner(name=name, executable=path, model=config.model,
                          effort=config.effort, timeout=config.timeout)
    return None
