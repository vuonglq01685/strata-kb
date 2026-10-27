import json
from pathlib import Path

from strata_kb import models
from strata_kb.l3check import report
from strata_kb.l3check.agent import (
    REASON_MAX_WORDS,
    annotate,
    build_prompt,
    parse_verdict,
)
from strata_kb.l3check.report import Finding, L3Check, SectionCheck
from strata_kb.llm import RunnerError

RAW = "## 1 A\n\nalpha body\n\n## 2 B\n\nbeta body\n"


def _kb(tmp_path: Path) -> Path:
    kb = tmp_path / ".kb"
    doc = kb / "doc"
    doc.mkdir(parents=True)
    models.save_yaml_model(
        kb / "index.yaml", models.KBIndex(docs=[models.IndexEntry(id="doc", title="D")])
    )
    sections = [
        models.SectionEntry(id=i, title=t, file="a")
        for i, t in (("1", "A"), ("2", "B"))
    ]
    models.save_yaml_model(
        doc / "_manifest.yaml", models.Manifest(id="doc", title="D", sections=sections)
    )
    (doc / "a.raw.md").write_text(RAW, encoding="utf-8")
    return kb


def _break(n: int = 0) -> Finding:
    return Finding(
        kind="break",
        page=1,
        evidence={"l3": f"tail {n}", "next": f"head {n}", "pdf": f"window {n}"},
    )


def _flag(kb: Path, findings_by_section: dict[str, list[Finding]]) -> None:
    digests = report.current_digests(kb, "doc")
    sections = [
        SectionCheck(id=sid, l3_sha256=digests[sid], findings=fs)
        for sid, fs in findings_by_section.items()
    ]
    report.save(kb / "doc", L3Check(checked_at="t", sections=sections))


class FakeRunner:
    def __init__(self, reply="""{"verdict": "spurious", "reason": "pdf wraps here"}"""):
        self.reply = reply
        self.prompts: list[str] = []

    def run(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


class BoomRunner:
    def run(self, prompt: str) -> str:
        raise RunnerError("x" * 300)


def test_parse_verdict_valid():
    v = parse_verdict('{"verdict": "intentional", "reason": "heading split"}')
    assert (v.verdict, v.reason) == ("intentional", "heading split")


def test_parse_verdict_fenced():
    v = parse_verdict('```json\n{"verdict": "spurious", "reason": "r"}\n```')
    assert v.verdict == "spurious"


def test_parse_verdict_garbage_is_unsure():
    for bad in ("", "no json here", '{"verdict": "maybe", "reason": "r"}', '{"a": 1}'):
        assert parse_verdict(bad).verdict == "unsure"


def test_parse_verdict_long_reason_truncated():
    reason = " ".join(f"w{i}" for i in range(REASON_MAX_WORDS + 20))
    v = parse_verdict(json.dumps({"verdict": "spurious", "reason": reason}))
    assert len(v.reason.split()) == REASON_MAX_WORDS


def test_prompt_forbids_rewrite():
    p = build_prompt(_break(7))
    assert "do not rewrite" in p
    assert all(s in p for s in ("tail 7", "head 7", "window 7"))


def test_annotate_only_break_findings_and_never_touches_raw_md(tmp_path):
    kb = _kb(tmp_path)
    content = Finding(kind="content", page=1)
    _flag(kb, {"1": [_break(1), content], "2": [_break(2)]})
    raw = kb / "doc" / "a.raw.md"
    before = raw.read_bytes()
    fake = FakeRunner()

    n = annotate(kb, "doc", fake, max_workers=2)

    assert n == 2
    assert len(fake.prompts) == 2
    assert raw.read_bytes() == before
    check = report.load(kb / "doc")
    assert check is not None
    s1, s2 = check.sections
    assert s1.findings[0].agent is not None
    assert s1.findings[0].agent.verdict == "spurious"
    assert s1.findings[1].agent is None
    assert s2.findings[0].agent is not None


def test_annotate_skips_findings_with_a_verdict_and_missing_file(tmp_path):
    kb = _kb(tmp_path)
    fake = FakeRunner()
    assert annotate(kb, "doc", fake, max_workers=1) == 0  # no _l3check.yaml
    done = _break(1).model_copy(
        update={"agent": report.AgentVerdict(verdict="unsure", reason="r")}
    )
    _flag(kb, {"1": [done]})
    assert annotate(kb, "doc", fake, max_workers=1) == 0
    assert fake.prompts == []


def test_annotate_runner_error_stores_unsure(tmp_path):
    kb = _kb(tmp_path)
    _flag(kb, {"1": [_break()]})

    assert annotate(kb, "doc", BoomRunner(), max_workers=1) == 1

    check = report.load(kb / "doc")
    assert check is not None
    v = check.sections[0].findings[0].agent
    assert v is not None
    assert v.verdict == "unsure"
    assert v.reason.startswith("agent error: ")
    assert len(v.reason) == len("agent error: ") + 100


def test_annotate_does_not_confirm(tmp_path):
    kb = _kb(tmp_path)
    _flag(kb, {"1": [_break()]})
    annotate(kb, "doc", FakeRunner(), max_workers=1)
    check = report.load(kb / "doc")
    assert check is not None
    assert check.sections[0].confirmed is None
