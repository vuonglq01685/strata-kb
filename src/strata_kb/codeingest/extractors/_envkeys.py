"""The one place a compose `environment:` block's *keys* are extracted and
sanitised (Ruling R40).

**Why this module exists.** This exact rule — "take only the key half of
an `environment:` entry, never the value" — has now caused a Critical
secret leak twice, in two different extractor modules that each kept
their own copy of it:

  - `services.py` (Task B4): its own `_sanitize_env_key` took three
    review rounds to close, because each round patched only the one
    branch of `_env_keys_from` a reported reproduction exercised.
  - `integrations.py` (Task B7): copied `services.py`'s already-fixed
    function verbatim, which *carried the fix for the round-3 defect
    forward correctly* but reintroduced a DIFFERENT bug the round-3 fix
    never had to consider, because nobody had reason to re-examine a
    function that looked already-hardened.

That second bug is the reason this module exists and looks the way it
does. The pre-R40 sanitiser was `str(raw).split("=", 1)[0]`, then
whitespace-collapse: "keep everything up to the first `=`". That is
correct when the source syntax genuinely uses `=` (`KEY=value`, or a
YAML-mangled single-pair mapping whose key text still contains a literal
`=`). It is **wrong** whenever the polluted string uses `:` instead —
which is exactly what happens when a compose `environment:` entry's
*key itself* was never a clean identifier to begin with (a stray `:` in
a list-string entry with no `=` at all, or a mapping key that legitimately
contains a colon because YAML took everything up to the *last* `": "` as
the key). With no `=` present, `.split("=", 1)[0]` is a no-op — the
*entire* string, credentials and all, was returned as the "key" and
published verbatim to `l2_md`, `l3_md`, and (via `integrations.py`'s
summary format string) `_manifest.yaml`.

**The fix**: stop trying to enumerate every delimiter a polluted string
might use. After splitting on the first `=` (still correct for the
`KEY=value` cases), require what's left to be *nothing but* a valid
key-shaped token — optionally preceded by whitespace and a shell-style
`export `, optionally followed by trailing whitespace — via
`_KEY_TOKEN_RE.fullmatch`. Anything left over after the token (a `:`, a
`/`, an `@`, whitespace, a second colon-delimited value, ...) means the
whole string was never a clean key to begin with, and `sanitize_env_key`
returns `""` for it — exactly like any other candidate that "sanitises
away to nothing" already did. This also makes the embedded-newline and
embedded-pipe cases moot: a leftover `\n` or `|` after the token fails
the full-string match too, for the same reason a leftover `:` does.

**Ruling R41 (round 2 of this fix): the token class was too narrow.**
The first version of `_KEY_TOKEN_RE` only accepted `[A-Za-z_][A-Za-z0-9_]*`
— a bare identifier. That silently dropped, with no warning, every
dotted or hyphenated key real compose files actually use (Elasticsearch/
Kibana's own documented `environment:` shape: `ES_JAVA_OPTS`,
`cluster.name`, `discovery.type`, `xpack.security.enabled`; also a
hyphenated name like `MY-APP_TOKEN`) — a service that legitimately
declares several such keys could silently render `Env keys: none`.
Widening the class to `[A-Za-z_][A-Za-z0-9_.-]*` (letters, digits,
underscore, dot, hyphen — after a leading letter or underscore) restores
those keys while changing nothing about what the fix actually closes:
`:`, `/`, `@`, and whitespace are still outside the class and still
cannot be absorbed by the token or by the trailing-whitespace match, so all three
of the Critical's original reproductions (a `:`-delimited list-string
value, a mapping key containing a colon, and the quoted-string variant)
remain rejected — re-verified explicitly after this change, not assumed.

Both `services.py` and `integrations.py` import from here rather than
keeping their own copy. Fix it once, in the one place that both modules
are required to use, and it cannot drift out of sync between them again.

**`redact_userinfo` (task review, Important 2).** A second, unrelated
class of committed credential: a URL's own `user:pass@` (or bare
`token@`) userinfo segment, sitting in plain sight in a PEP 508 direct-URL
Python dependency, an npm `git+https://token@...` git dependency, an
OpenAPI `servers[*].url`, or a shell command a `commands.py` reader
happens to capture verbatim. None of those are secret *channels* the way
a compose `environment:` value is — the precondition is always a
credential the Dev already committed to source in plaintext — but
`.kb/`'s `_snapshot` syncs the *entire* KB directory to the federation
hub, an audience wider than the source repo a plaintext credential might
otherwise only ever be seen by. `deps.py`, `commands.py`, and `api.py`
all import `redact_userinfo` from here rather than keeping their own
copy, for the same "fix it once" reason `env_keys_from` lives here."""
from __future__ import annotations

import re

# Matches an env-var-shaped token and *only* that token: optional leading
# whitespace, an optional shell "export " prefix, then a key-shaped token
# (a leading letter/underscore, then letters/digits/underscore/dot/hyphen
# -- Ruling R41 widened this from a bare identifier to also accept the
# dotted/hyphenated keys real compose files use, e.g. Elasticsearch's
# `cluster.name` or a hyphenated `MY-APP_TOKEN`), then optional trailing
# whitespace. Used with `.fullmatch()`, never `.match()` -- the whole
# remainder must be consumed, or the candidate is rejected outright
# rather than truncated to its token-shaped prefix (see module
# docstring: truncating instead of rejecting is exactly how the Critical
# leaked a `:`-delimited value that happened to start with a real key --
# `:`, `/`, `@`, and whitespace are still outside the class, so widening
# it does not reopen that leak).
_KEY_TOKEN_RE = re.compile(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.\-]*)\s*")


def sanitize_env_key(raw: object) -> str:
    """(1) Coerce to `str` (a YAML mapping key need not already be one).
    (2) Split on the first `"="` and keep only the part before it — the
    `KEY=value` convention, and the part of a YAML-mangled
    single-pair-mapping key that is actually the key. (3) Require the
    *entire* remainder to be a key-shaped token (`_KEY_TOKEN_RE`,
    full-string match — letters/digits/underscore/dot/hyphen after a
    leading letter or underscore, Ruling R41) — a `:`-delimited value
    with no `=` at all, an embedded newline, or any other leftover text
    after the token means the candidate was never a clean key, so it is
    rejected, not truncated to its token-shaped prefix. Returns `""` for
    anything that doesn't sanitise down to a clean key; every caller
    guards on non-empty before using the result."""
    text = str(raw).split("=", 1)[0]
    match = _KEY_TOKEN_RE.fullmatch(text)
    return match.group(1) if match else ""


def env_keys_from(value: object) -> list[str]:
    """Extract every candidate key from a compose `environment:` block,
    across every shape YAML can hand back for it: a top-level mapping
    (`{KEY: value}`), a list of `KEY=value` strings, and the
    list-of-single-pair-mapping shape YAML produces when a `KEY=value`
    list entry's own text contains `": "` (so the loader reads that one
    entry as a one-pair mapping, not a scalar). Every branch below reads
    only a mapping's or sequence's *keys* — no branch ever reads a
    value — and every key is routed through `sanitize_env_key` before
    being kept.

    Returned in encounter order, **not** deduplicated or sorted: callers
    that only need a flat set (`services.py`) apply `sorted(set(...))`
    themselves; callers that track per-key metadata (`integrations.py`,
    which records which file(s) contributed each key) need the raw,
    unsorted, undeduplicated sequence."""
    keys: list[str] = []
    if isinstance(value, dict):
        for raw_key in value:
            key = sanitize_env_key(raw_key)
            if key:
                keys.append(key)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                key = sanitize_env_key(item)
                if key:
                    keys.append(key)
            elif isinstance(item, dict):
                for raw_key in item:
                    key = sanitize_env_key(raw_key)
                    if key:
                        keys.append(key)
    return keys


# Matches a URL scheme followed by a userinfo segment up to the "@" that
# ends it -- "user:pass@" or a bare "token@" (no colon at all, the shape a
# GitHub personal-access-token dependency URL commonly uses). Excludes "/"
# and whitespace from the userinfo class so this never reaches past the
# "@" into an unrelated path segment or a later, unrelated URL.
_USERINFO_RE = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*://)[^/@\s]+@")


def redact_userinfo(text: str) -> str:
    """Rewrite every `scheme://user:pass@` (or bare `scheme://token@`)
    found in `text` to `scheme://***@`, leaving the scheme and host
    intact. Safe to call on text with no such URL at all (a no-op) and on
    text with several (each is masked independently)."""
    return _USERINFO_RE.sub(lambda m: f"{m.group('scheme')}***@", text)
