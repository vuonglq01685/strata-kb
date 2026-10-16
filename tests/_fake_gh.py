"""Shared fake for `ghrest._gh`: records REST calls, answers from canned routes."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Call:
    host: str
    method: str
    path: str
    body: dict | None


class FakeGh:
    def __init__(self) -> None:
        self.calls: list[Call] = []
        self._routes: list[tuple[str, str, list]] = []

    def on(self, method: str, path_part: str, *responses) -> None:
        """Answer `method` calls whose path contains `path_part`; responses are
        consumed in order, the last one repeats. An Exception instance raises."""
        self._routes.append((method, path_part, list(responses)))

    def __call__(self, root, args, stdin=None) -> str:
        assert args[0] == "api", args
        host = args[args.index("--hostname") + 1]
        i = args.index("-X")
        method, path = args[i + 1], args[i + 2]
        body = json.loads(stdin) if stdin is not None else None
        if body is not None:
            assert args[i + 3 : i + 5] == ["--input", "-"], args
        self.calls.append(Call(host, method, path, body))
        for m, part, responses in self._routes:
            if m == method and part in path:
                resp = responses.pop(0) if len(responses) > 1 else responses[0]
                if isinstance(resp, Exception):
                    raise resp
                return "" if resp is None else json.dumps(resp)
        raise AssertionError(f"unexpected call {method} {path}")


def rest_pr(
    number=7,
    state="open",
    merged_at=None,
    head="auto/US-1",
    sha="abc123",
    title="T",
    body="B",
) -> dict:
    return {
        "number": number,
        "html_url": f"https://github.com/o/r/pull/{number}",
        "state": state,
        "merged_at": merged_at,
        "title": title,
        "body": body,
        "head": {"ref": head, "sha": sha},
    }


def make_repo(tmp_path: Path, remote: str = "https://github.com/o/r.git") -> Path:
    def git(*a: str) -> None:
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "auto/US-1")
    git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "i",
    )
    git("remote", "add", "origin", remote)
    git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    return tmp_path
