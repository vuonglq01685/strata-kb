"""Stable, unique id slugs — shared by `services` (`svc.<slug>`) and every
extractor that needs a per-file or per-name id.

A slug depends only on the name it is built from, never on sibling order or
on which siblings happen to be present in one run, so ids stay stable when
an unrelated name is added or removed. Callers pass names as they want them
slugged (e.g. a repo-relative path without its suffix).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from strata_kb.mdutils import slugify_id

_NAME_NORMALIZE_RE = re.compile(r"[\W_]+")


def _normalize_name(name: str) -> str:
    """The same normalization `mdutils.slugify_id` applies (NFKC,
    `[\\W_]+` -> `-`, strip, lower) but WITHOUT its 40-char cap. Used as
    the *dedupe* key so `api_gateway` and
    `api-gateway` (spelling drift — DNS-1123 forbids underscores in k8s
    names but compose allows them) still merge, while
    two distinct 40+ character names that only coincide *after*
    truncation are correctly treated as different services and are never
    silently merged (that would delete one of them with zero
    warnings)."""
    text = unicodedata.normalize("NFKC", name)
    return _NAME_NORMALIZE_RE.sub("-", text).strip("-").lower()


def _safe_slug(name: str) -> str:
    """`slugify_id(name)`, guaranteed non-empty. A name made
    entirely of punctuation/emoji/underscores (or an empty raw name, e.g.
    a compose `services: {"": {...}}` key) normalizes to `""` via
    `slugify_id`'s own regex, which would ship the degenerate public join
    key `id="svc."`. Falls back to a short, deterministic hash of the
    *raw* name — never a sibling-order index — so two different
    degenerate names still get different fallback ids."""
    slug = slugify_id(name)
    if slug:
        return slug
    return f"unnamed-{hashlib.sha256(name.encode('utf-8')).hexdigest()[:8]}"


def _stable_suffix(seed: str) -> str:
    """A short suffix derived only from `seed` (the record's own full
    normalized name) — never from sibling order or an index — so a
    truncation-collision disambiguation never shifts
    a service's id when an unrelated sibling service is added or
    removed. `kb svc note` validates ticket <-> service history
    against this id, so its stability matters more than its brevity."""
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:6]


# Must match `mdutils.slugify_id`'s own truncation length exactly — this
# is what determines whether *this* record's name could possibly collide
# with another after `slugify_id` truncates it.
_ID_CAP = 40


def assign_slugs(names: list[str]) -> list[str]:
    """One safe, unique id slug per (already-deduped) name — parallel
    to `names`.

    The disambiguation suffix must come only from a record's own full
    normalized name — never from sibling order or an index — so a
    service's id never shifts merely because an unrelated sibling was
    added or removed in some run. Do not add a suffix only when an
    *actual* collision is detected among the records passed in for one
    call: that technically doesn't use sibling order or an index, but
    still makes the presence of the suffix depend on which siblings
    happen to be present, which is exactly the instability to avoid
    (`test_truncation_collision_id_is_stable_when_a_sibling_is_removed`
    catches that approach).

    The per-record pass below avoids it: whether a record's id gets a
    suffix depends *only* on that record's own normalized name length
    relative to `_ID_CAP` — never on whether any other record happens to
    share the same truncated prefix in this particular run. Every name
    whose full normalized form exceeds `_ID_CAP` is unconditionally
    suffixed; every name at or under the cap never is. Two already-
    deduped records both at-or-under the cap can never collide *by
    length* (their `_safe_slug()` equals their full `_normalize_name()`
    unchanged, and `_dedupe`'s key is that same `_normalize_name()`, so
    two distinct post-dedupe records already have distinct short slugs);
    two both over the cap get distinct name-derived suffixes; one over
    and one under can only coincide if the short one is a
    truncation-length prefix of the long one, and the long one's
    mandatory suffix breaks that tie too.

    What the per-record pass does NOT cover — it is not "collision-free
    by construction, no need to inspect siblings at all":
    `_safe_slug()`'s hash fallback (`"unnamed-<sha256[:8]>"`,
    used when a name normalizes to `""`) shares its plain-string output
    format with ordinary slugs, so it can coincide with a REAL service
    that happens to be named exactly that fallback string (e.g. one
    service named `"+++"` and another literally named
    `"unnamed-29f5099b"` — verified to be `slugify_id("+++")`'s actual
    fallback value). That is a coincidence between two different records'
    outputs, not a property either record's own name-length check can
    see in isolation, so it genuinely does need a final cross-record
    pass. That pass never picks a "winner": every member of a still-
    colliding group gets a further name-derived suffix, so no record is
    silently left with the bare, ambiguous slug."""
    slugs: list[str] = []
    for name in names:
        base = _safe_slug(name)
        normalized = _normalize_name(name)
        if len(normalized) > _ID_CAP:
            slugs.append(f"{base}-{_stable_suffix(normalized)}")
        else:
            slugs.append(base)

    # Final uniqueness pass: closes the `_safe_slug` hash-fallback-namespace
    # collision above (and, incidentally, the residual birthday-paradox
    # risk of `_stable_suffix`'s 24-bit space) without ever choosing
    # which colliding record keeps the unsuffixed form.
    counts: dict[str, int] = {}
    for slug in slugs:
        counts[slug] = counts.get(slug, 0) + 1
    for i, name in enumerate(names):
        if counts[slugs[i]] > 1:
            slugs[i] = f"{slugs[i]}-{_stable_suffix(name)}"
    return slugs
