"""Kubernetes `kind: CronJob` reader for `jobs.py`.

Read with PyYAML's compose step only (no tree-sitter, so it works without
the `code` extra) so every value keeps its line. A schedule that is not a
plain literal (Helm `{{ ... }}`, a flow mapping) is `(dynamic)`. Names only:
the job is `metadata.name`, the handler its container names; images,
commands and env are never read.
"""

from __future__ import annotations

import yaml

from strata_kb.codeingest.extractors._jobs_model import (
    DYNAMIC,
    Job,
    name_only,
    plain,
    schedule_only,
)


def _mapping(node: yaml.Node | None) -> dict[str, yaml.Node]:
    if not isinstance(node, yaml.MappingNode):
        return {}
    return {k.value: v for k, v in node.value if isinstance(k, yaml.ScalarNode)}


def _scalar(node: yaml.Node | None) -> str | None:
    return plain(node.value) if isinstance(node, yaml.ScalarNode) else None


def _name(node: yaml.Node | None) -> str | None:
    return name_only(_scalar(node))


def _containers(spec: dict[str, yaml.Node]) -> str:
    pod = _mapping(
        _mapping(
            _mapping(_mapping(spec.get("jobTemplate")).get("spec")).get("template")
        ).get("spec")
    )
    listed = pod.get("containers")
    names = (
        [_name(_mapping(c).get("name")) for c in listed.value]
        if isinstance(listed, yaml.SequenceNode)
        else []
    )
    return ", ".join(n for n in names if n) or "-"


def _cronjob(rel: str, doc: yaml.Node) -> tuple[Job, str | None]:
    root = _mapping(doc)
    spec = _mapping(root.get("spec"))
    sched = spec.get("schedule")
    schedule = schedule_only(_scalar(sched))
    line = (sched or doc).start_mark.line + 1
    site = f"{rel}:{line}" if schedule is None else None
    name = _name(_mapping(root.get("metadata")).get("name"))
    if name is None:
        name = DYNAMIC
        site = site or f"{rel}:{doc.start_mark.line + 1}"
    job = Job(
        name, " ".join((schedule or DYNAMIC).split()), _containers(spec), rel, line
    )
    return job, site


def _documents(
    rel: str, doc: yaml.Node | None, sites: list[str], implicit: bool = False
) -> list[yaml.Node]:
    """The CronJob mappings of one YAML document, unwrapping `kind: List`
    (`implicit`: the items of a `CronJobList` need no kind of their own)."""
    root = _mapping(doc)
    kind = _scalar(root.get("kind")) or ("CronJob" if implicit else None)
    if kind == "CronJob" and doc is not None:
        return [doc]
    if kind is not None and kind.endswith("List") and "items" in root:
        items = root["items"]
        if not isinstance(items, yaml.SequenceNode):
            sites.append(f"{rel}:{items.start_mark.line + 1}")
            return []
        return [
            d
            for item in items.value
            for d in _documents(rel, item, sites, kind == "CronJobList")
        ]
    return []


def scan(rel: str, text: str) -> tuple[list[Job], list[str]]:
    """(jobs, `file:line` sites) of one YAML file. A file PyYAML cannot read
    (a Helm template, absurd nesting) is one `file:1` site."""
    try:
        docs = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
        jobs: list[Job] = []
        sites: list[str] = []
        for doc in docs:
            for cron in _documents(rel, doc, sites):
                job, site = _cronjob(rel, cron)
                jobs.append(job)
                if site is not None:
                    sites.append(site)
    except (yaml.YAMLError, RecursionError):
        return [], [f"{rel}:1"]
    return jobs, sites
