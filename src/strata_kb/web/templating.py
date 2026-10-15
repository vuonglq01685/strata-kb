"""templating — the Jinja environment for the web UI's HTML templates.

`make_env` loads `strata_kb/templates/web` with autoescaping on for `.html`
and by default; `render` renders one template from a shared module-level
environment. Autoescaping is what keeps template output XSS-safe, so keep it
on.
"""

from __future__ import annotations

from jinja2 import Environment, PackageLoader, select_autoescape

import strata_kb


def make_env() -> Environment:
    env = Environment(
        loader=PackageLoader("strata_kb", "templates/web"),
        autoescape=select_autoescape(enabled_extensions=("html",), default=True),
    )
    # /ui/static/* is cached for a day: versioned URLs make an upgrade fetch fresh files.
    env.globals["asset_v"] = strata_kb.__version__
    return env


_env = make_env()


def render(template: str, **ctx) -> str:
    return _env.get_template(template).render(**ctx)
