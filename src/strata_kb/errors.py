"""Shared base for center_kb's operational errors.

Every domain error a CLI command turns into a clean, one-line, exit-1
message -- instead of letting a raw traceback reach the user -- should
derive from `KbError` rather than `RuntimeError` directly. A CLI guard can
then catch `KbError` once and mean "every error this call path already
converts into a user-facing message", instead of re-enumerating
`PublishError` / `GateError` / `CIPublishError` / `AssetStoreError` / ... at
every call site.

That enumeration is what kept failing in this batch: a new sibling (or a new
call site for an existing one) is added, one `except (...)` tuple is not
updated, and the class it misses stops being "caught and turned into a
message" and starts being "an uncaught traceback" -- silently, because nine
other tuples nearby still look complete. Catching the base instead makes
completeness structural -- PROVIDED something actually enforces that every
CLI-terminal sibling joins the family. A hardcoded tuple of class names in a
test cannot do that (a fifth sibling nobody adds to the tuple is invisible to
it -- proven: `ManifestBoundsError(RuntimeError)` was added on the live `kb
publish` path with the full suite staying green and the CLI printing a bare
traceback). `tests/test_cli_errors.py`'s
`test_every_cli_terminal_exception_joins_kb_error_or_is_allowlisted`
discovers every module-level exception class defined in a module
`pkgutil.walk_packages` reaches (`center_kb.__path__`, scoped to `Exception`
so a sibling outside the `RuntimeError` family is not invisible either) and
requires each one to either derive from `KbError` or be named in that test's
allowlist with a reason -- that is what makes a sibling which forgets to join
fail on its own, rather than reaching a user's terminal. One narrower claim
than "every exception class center_kb defines": `pkgutil`'s file-finder skips a
directory with no `__init__.py` (a PEP 420 namespace portion) as "not a
package", so a class defined only there is not swept -- latent today, since
every subpackage in this tree has an `__init__.py` (Minor 3, Wave G fix
round 2 re-review).

Deriving from `RuntimeError` (not replacing it) keeps every existing
`except PublishError`, `except GateError`, `except SomeSpecificSubclass` and
`except RuntimeError` working unchanged -- this is purely additive.
"""
from __future__ import annotations


class KbError(RuntimeError):
    """Base for center_kb errors a CLI command converts into a one-line,
    exit-1 message naming the way forward, rather than letting propagate."""
