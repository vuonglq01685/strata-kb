"""Guards against Windows-breaking patterns (spec 2026-07-14-windows-support).

subprocess text=True without encoding decodes with the locale codepage
(cp1252) on Windows — UTF-8 output from git/claude gets mojibaked."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src" / "center_kb"
SCRIPTS = ROOT / "scripts"


def _windows(text: str, needle: str, span: int = 300) -> list[str]:
    """A ±span-char window around each occurrence of needle."""
    return [
        text[max(0, m.start() - span): m.start() + span]
        for m in re.finditer(re.escape(needle), text)
    ]


def test_subprocess_text_true_always_sets_utf8():
    offenders = []
    for py in sorted(SRC.rglob("*.py")):
        text = py.read_text(encoding="utf-8")
        for window in _windows(text, "text=True"):
            if 'encoding="utf-8"' not in window:
                offenders.append(str(py.relative_to(SRC)))
    assert not offenders, (
        f"subprocess text=True without encoding=\"utf-8\" in: {offenders} — "
        "on Windows this decodes with cp1252 and mojibakes UTF-8 output"
    )


# Inverted from a hardcoded module list (M16): the old version guarded six
# files, and svcnote.py / codeingest/core.py / usage/ledger.py wrote
# committed content outside it. A scan cannot drift the way a list can — but
# only once it can actually see every write shape. Round 1 found it missed
# `path.open("a")`-style method calls (I1), which is exactly how
# usage/ledger.py and cli.py write their committed usage logs; see
# _open_mode. A new writer now fails until someone states, at the call site,
# why it is exempt.
EXEMPT_MARKER = "newline-exempt:"


_MODE_CHARS = set("rwaxbt+")


def _open_mode(node: ast.Call) -> str:
    """The mode string of an open(...)-shaped call, positional or by keyword.

    Bug found in Step 5 (M16): the original snippet re-derived this from
    `call.args[1:2]` only, so `open(path, mode="wb")` (mode by keyword) was
    never recognised as binary and would misfire as an offender. One helper,
    reused by both the collector and the binary-mode skip below, so the two
    can't disagree about what "mode" means for a given call.

    I1 (round 1): a *method* call (`path.open("a")`) has no leading path
    argument, so its mode is args[0], not args[1] like the builtin
    `open(path, "a")`. Missing this let two committed-content writers go
    completely unseen by the scan.

    Round 2: I1's fix keyed on `isinstance(node.func, ast.Attribute)` alone,
    so it also applied to `write_text` (also an attribute call) and read its
    *content* string as a mode -- any content literal containing "b" (e.g.
    "debug output") silently took the binary skip below. Fix: (1) only a
    call actually named `open` gets a mode at all -- everything else is `""`;
    (2) for `open`, don't guess a fixed argument index -- scan args[0] then
    args[1] and take the first string constant that is *shaped* like a mode
    (only characters from `rwaxbt+`). That's what lets `p.open("w")` (mode at
    0), `open(p, "w")` and `io.open(p, "w")` (path at 0 isn't mode-shaped, so
    mode is at 1), and `open("file.txt", "w")` (the filename isn't
    mode-shaped either) all resolve correctly with one rule.
    """
    name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
    if name != "open":
        return ""
    mode = ""
    for arg in node.args[:2]:
        if (
            isinstance(arg, ast.Constant)
            and isinstance(arg.value, str)
            and arg.value
            and set(arg.value) <= _MODE_CHARS
        ):
            mode = arg.value
            break
    for kw in node.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = str(kw.value.value)
    return mode


def _write_calls(tree: ast.AST) -> list[ast.Call]:
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name == "write_text":
            out.append(node)
        elif name == "open" and any(c in _open_mode(node) for c in "wax"):
            out.append(node)
    return out


def _exempt_window(lines: list[str], call: ast.Call) -> str:
    """Comment lines directly above the call, plus the call's own span.

    I3 (round 1): a fixed lookback distance breaks the moment someone writes
    a longer reason -- it did, twice, for this task's own exemption comments,
    while the marker sat right there in the source. Walking upward over
    contiguous `#` comment lines instead means there is no fixed size to
    outgrow.
    """
    top = call.lineno - 1  # 0-indexed row of the call's first line
    while top > 0 and lines[top - 1].strip().startswith("#"):
        top -= 1
    end = call.end_lineno or call.lineno
    return "\n".join(lines[top:end])


def test_every_text_writer_forces_lf_or_says_why_not():
    offenders = []
    seen = 0
    paths = sorted(SRC.rglob("*.py")) + sorted(SCRIPTS.rglob("*.py"))
    for py in paths:
        text = py.read_text(encoding="utf-8")
        lines = text.splitlines()
        tree = ast.parse(text)
        for call in _write_calls(tree):
            seen += 1
            # I2: the kwarg's VALUE matters, not just its presence --
            # newline=None (the CRLF-translating default) or newline="\r\n"
            # must not pass as compliant.
            newline_value = next(
                (kw.value for kw in call.keywords if kw.arg == "newline"), None
            )
            if isinstance(newline_value, ast.Constant) and newline_value.value == "\n":
                continue
            if "b" in _open_mode(call):
                continue  # binary mode has no newline translation
            if EXEMPT_MARKER in _exempt_window(lines, call):
                continue
            offenders.append(f"{py.relative_to(ROOT)}:{call.lineno}")
    # Final review item 3: stubbing _write_calls to return [] left this test
    # green (verified) -- nothing pinned that the collector actually SEES
    # any writer. A floor is weaker than the positive-direction test below
    # (it can't prove a REAL offender gets caught, only that something was
    # counted), so it's a backstop, not the main proof.
    assert seen >= 20, (
        f"only {seen} write call(s) seen -- the collector may have gone "
        "blind (expected dozens across src/ and scripts/)"
    )
    assert not offenders, (
        "text writers without newline=\"\\n\" and without a "
        f"'# {EXEMPT_MARKER} <reason>' comment: {offenders} — CRLF from a "
        "Windows machine churns hub diffs and skews content digests"
    )


def _offenders_in_source(src: str) -> list[int]:
    """The same per-call verdict test_every_text_writer_forces_lf_or_says_why_not
    runs, factored out so it can be proven against a synthetic source string
    instead of only ever running over today's real files."""
    lines = src.splitlines()
    tree = ast.parse(src)
    out = []
    for call in _write_calls(tree):
        newline_value = next(
            (kw.value for kw in call.keywords if kw.arg == "newline"), None
        )
        if isinstance(newline_value, ast.Constant) and newline_value.value == "\n":
            continue
        if "b" in _open_mode(call):
            continue
        if EXEMPT_MARKER in _exempt_window(lines, call):
            continue
        out.append(call.lineno)
    return out


def test_the_scan_catches_an_unmarked_writer_and_clears_a_compliant_one():
    """Positive-direction proof the reviewer asked for: an unmarked text
    writer must be reported; the same writer with newline="\\n" or a
    '# newline-exempt:' comment above it must not be."""
    assert _offenders_in_source("open(path, 'w').write(data)\n") == [1]
    assert _offenders_in_source(
        'open(path, "w", newline="\\n").write(data)\n'
    ) == []
    assert _offenders_in_source(
        "# newline-exempt: binary-safe test double, not committed content\n"
        "open(path, 'w').write(data)\n"
    ) == []
