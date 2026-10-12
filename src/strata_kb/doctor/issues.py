"""The doctor's issue type and the helpers every check shares."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import ValidationError

if TYPE_CHECKING:
    pass


# did not parse, did not validate, or is not UTF-8.
_CONFIG_READ_ERRORS = (yaml.YAMLError, ValidationError, ValueError)


@dataclass
class Issue:
    """One doctor, ticket-lint or mission-lint result. `prlint.Finding` and
    `quality.Finding` are separate on purpose: other levels, other keys."""

    level: Literal["error", "warning", "info"]
    message: str
    # A stable machine tag for the checks a caller needs to tell apart —
    # today only "stale-ref", so `kb ticket lint --fail-on-stale` can
    # report exit code 2 ("only staleness failed") the way `kb resolve`
    # does. Defaulted, so every existing construction is unchanged.
    code: str = ""


def _flatten(exc: Exception) -> str:
    """Collapse a (possibly multi-line) exception message to one scannable line."""
    return " ".join(str(exc).split())
