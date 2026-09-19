from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass

from strata_kb.models import LLMConfig

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
        """One headless call; returns the model's reply text.

        The prompt ALWAYS travels on stdin: an argv prompt is cut at the
        first newline and %VAR%-expanded by cmd.exe when the executable is
        an npm `.cmd` shim on Windows (review B-1), and hits ARG_MAX on
        every platform for long sections.

        copilot: no `-p`/`--prompt` flag is passed — GitHub's docs say to
        pipe the prompt (`echo "..." | copilot`) and that "Piped input is
        ignored if you also provide a prompt with the -p or --prompt
        option" (docs.github.com/en/copilot/how-tos/copilot-cli/
        automate-copilot-cli/run-cli-programmatically). `-p` takes a value
        (docs.github.com/en/copilot/reference/copilot-cli-reference/
        cli-programmatic-reference), so a bare `-p` would consume
        `--model` as the prompt and ignore stdin entirely (controller
        ruling R7)."""
        if self.name == "claude":
            cmd = [self.executable, "-p", "--model", self.model, "--output-format", "json"]
        else:
            # copilot: prompt arrives on stdin only; -s drops metadata
            cmd = [self.executable, "--model", self.model, "-s"]
        if prompt in cmd:
            raise RunnerError("prompt must travel on stdin, not argv")
        env = None
        if self.name == "claude" and self.effort == "high":
            env = os.environ | {"MAX_THINKING_TOKENS": HIGH_EFFORT_THINKING_TOKENS}
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=self.timeout, env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise RunnerError(f"{self.name}: timed out after {self.timeout}s") from exc
        if proc.returncode != 0:
            raise RunnerError(f"{self.name}: exit {proc.returncode}: {proc.stderr.strip()[:500]}")
        return _extract_reply(self.name, proc.stdout)


def _extract_reply(name: str, stdout: str) -> str:
    if name != "claude":
        return stdout.strip()
    # claude --output-format json wraps the reply: {"type":"result","result":"…"}
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout.strip()  # older CLI: plain text
    if not isinstance(envelope, dict):
        return stdout.strip()
    subtype = str(envelope.get("subtype", ""))
    if envelope.get("is_error") or subtype.startswith("error"):
        detail = str(envelope.get("result") or subtype or "error")[:500]
        raise RunnerError(f"claude: {detail}")
    result = envelope.get("result")
    if not isinstance(result, str):
        raise RunnerError("claude: no result in envelope")
    return result.strip()


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
