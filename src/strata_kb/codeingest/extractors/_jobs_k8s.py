"""Kubernetes `kind: CronJob` reader for `jobs.py`.

Read with PyYAML's compose step only (no tree-sitter, so it works without
the `code` extra) so every value keeps its line. A schedule that is not a
plain literal (Helm `{{ ... }}`, a flow mapping) is `(dynamic)`. Names only:
the job is `metadata.name`, the handler its container names; images,
commands and env are never read.
"""

from __future__ import annotations

import yaml

from strata_kb.codeingest.extractors._jobs_model import DYNAMIC, Job, plain


def _mapping(node: yaml.Node | None) -> dict[str, yaml.Node]:
    if not isinstance(node, yaml.MappingNode):
        return {}
    return {k.value: v for k, v in node.value if isinstance(k, yaml.ScalarNode)}


def _scalar(node: yaml.Node | None) -> str | None:
    return plain(node.value) if isinstance(node, yaml.ScalarNode) else None


def _containers(spec: dict[str, yaml.Node]) -> str:
    pod = _mapping(
        _mapping(
            _mapping(_mapping(spec.get("jobTemplate")).get("spec")).get("template")
        ).get("spec")
    )
    listed = pod.get("containers")
    names = (
        [_scalar(_mapping(c).get("name")) for c in listed.value]
        if isinstance(listed, yaml.SequenceNode)
        else []
    )
    return ", ".join(n for n in names if n) or "-"


def scan(rel: str, text: str) -> tuple[list[Job], list[str]]:
    """(jobs, `file:line` sites) of one YAML file; never raises."""
    try:
        docs = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return [], [f"{rel}:1"]
    jobs: list[Job] = []
    sites: list[str] = []
    for doc in docs:
        root = _mapping(doc)
        if _scalar(root.get("kind")) != "CronJob":
            continue
        spec = _mapping(root.get("spec"))
        sched = spec.get("schedule")
        schedule = _scalar(sched)
        line = (sched or doc).start_mark.line + 1
        if schedule is None:
            schedule = DYNAMIC
            sites.append(f"{rel}:{line}")
        name = _scalar(_mapping(root.get("metadata")).get("name")) or DYNAMIC
        jobs.append(Job(name, " ".join(schedule.split()), _containers(spec), rel, line))
    return jobs, sites
