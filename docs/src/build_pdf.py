#!/usr/bin/env python3
"""Render the Markdown sources in this directory to PDFs in docs/.

Rebuild by hand on Windows, Linux or macOS:

    uv run --extra docs python docs/src/build_pdf.py [name ...]

uv uses the xhtml2pdf/reportlab/markdown versions pinned in uv.lock, so
pagination is the same on every machine. Without uv,
`pip install -e ".[docs]"` works but takes the newest versions, whose
line breaking may differ.

Fonts are vendored in docs/src/fonts: Liberation Sans/Mono 2.1.5 (SIL OFL
1.1), metric-compatible with Arial/Courier New and carrying the full
Vietnamese diacritic set that ReportLab's built-in Helvetica lacks. A glyph
none of them can draw, or any other xhtml2pdf warning (a font it could
not read, a fallback to Helvetica), fails the build and leaves the old PDF
in place.
"""

from __future__ import annotations

import io
import logging
import sys
from datetime import date
from pathlib import Path

import markdown
from xhtml2pdf import pisa
from xhtml2pdf.config.resources import ResourceAccessPolicy

SRC = Path(__file__).resolve().parent
OUT = SRC.parent
REPO_ROOT = OUT.parent
FONT_DIR = SRC / "fonts"

TITLES = {
    "architecture.en": ("Strata — Architecture", "Knowledge Base as Code"),
    "architecture.vi": ("Strata — Kiến trúc hệ thống", "Knowledge Base as Code"),
    "guide-hub-child.en": (
        "Strata — Hub & Child Guide",
        "For knowledge owners and authors",
    ),
    "guide-hub-child.vi": (
        "Strata — Hướng dẫn Hub & Child",
        "Dành cho người quản trị và biên soạn tri thức",
    ),
    "guide-ba.en": ("Strata — BA Guide", "For business analysts"),
    "guide-ba.vi": ("Strata — Hướng dẫn BA", "Dành cho Business Analyst"),
    "guide-dev.en": ("Strata — Developer Guide", "For engineers implementing tickets"),
    "guide-dev.vi": (
        "Strata — Hướng dẫn Developer",
        "Dành cho kỹ sư triển khai ticket",
    ),
}

CSS = """
@page {
  size: a4 portrait;
  margin: 20mm 18mm 18mm 18mm;
  @frame footer { -pdf-frame-content: footer; bottom: 9mm; left: 18mm; right: 18mm; height: 8mm; }
}

@font-face { font-family: Body; src: url("FONT_BODY_REGULAR"); }
@font-face { font-family: Body; src: url("FONT_BODY_BOLD"); font-weight: bold; }
@font-face { font-family: Body; src: url("FONT_BODY_ITALIC"); font-style: italic; }
@font-face { font-family: Body; src: url("FONT_BODY_BOLDITALIC"); font-weight: bold; font-style: italic; }
@font-face { font-family: Mono; src: url("FONT_MONO_REGULAR"); }
@font-face { font-family: Mono; src: url("FONT_MONO_BOLD"); font-weight: bold; }

body { font-family: Body; font-size: 9.5pt; line-height: 1.45; color: #1c1c1e; }

.cover { -pdf-keep-with-next: true; margin-bottom: 14mm; }
.cover .rule { background-color: #1f4e79; height: 3.2mm; margin-bottom: 6mm; }
.cover h1 { font-size: 25pt; color: #12314d; margin: 0 0 2mm 0; border: none; padding: 0; }
.cover .sub { font-size: 12pt; color: #5a6672; margin: 0 0 5mm 0; }
.cover .meta { font-size: 8.5pt; color: #7a848e; }

h1 { font-size: 16pt; color: #12314d; margin: 9mm 0 3mm 0;
     border-bottom: 0.7mm solid #1f4e79; padding-bottom: 1.6mm; }
h2 { font-size: 12.5pt; color: #1f4e79; margin: 7mm 0 2.4mm 0; }
h3 { font-size: 10.5pt; color: #2c3e50; margin: 5mm 0 1.8mm 0; }
h4 { font-size: 9.8pt; color: #3a4b5c; margin: 4mm 0 1.5mm 0; }

p { margin: 0 0 2.6mm 0; text-align: justify; }
ul, ol { margin: 0 0 2.8mm 5mm; }
li { margin-bottom: 1.2mm; }

a { color: #1f4e79; }
code { font-family: Mono; font-size: 8.6pt; background-color: #eef1f5; color: #0f3a5f; }

pre {
  font-family: Mono; font-size: 8pt; line-height: 1.32;
  background-color: #f5f7fa; border: 0.25mm solid #d6dde5;
  border-left: 1.1mm solid #1f4e79;
  padding: 2.6mm 3mm; margin: 0 0 3.4mm 0; color: #22313f;
}

table { width: 100%; border: 0.25mm solid #c8d2dc; margin: 0 0 3.6mm 0;
        -pdf-keep-in-frame-mode: shrink; }
th { background-color: #1f4e79; color: #ffffff; font-weight: bold;
     font-size: 8.4pt; padding: 1.8mm 2mm; text-align: left; }
td { font-size: 8.4pt; padding: 1.6mm 2mm; border-bottom: 0.2mm solid #dfe5ec;
     vertical-align: top; }

blockquote { margin: 0 0 3.2mm 0; padding: 2.4mm 3mm;
             background-color: #fdf6e3; border-left: 1.1mm solid #d9a300;
             color: #4a3c10; font-size: 9pt; }

hr { border: none; border-top: 0.25mm solid #d6dde5; margin: 6mm 0; }

#footer { font-family: Body; font-size: 7.5pt; color: #96a0aa;
          border-top: 0.2mm solid #e2e7ec; padding-top: 1.4mm; }
"""

PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{css}</style></head>
<body>
<div class="cover">
  <div class="rule"></div>
  <h1>{title}</h1>
  <div class="sub">{subtitle}</div>
  <div class="meta">strata-kb v{version} &nbsp;&middot;&nbsp; {stamp}</div>
</div>
{body}
<div id="footer">{title} &nbsp;&middot;&nbsp; strata-kb v{version}
  &nbsp;&middot;&nbsp; <pdf:pagenumber> / <pdf:pagecount></div>
</body></html>
"""


FONT_FILES = {
    "FONT_BODY_REGULAR": "LiberationSans-Regular.ttf",
    "FONT_BODY_BOLD": "LiberationSans-Bold.ttf",
    "FONT_BODY_ITALIC": "LiberationSans-Italic.ttf",
    "FONT_BODY_BOLDITALIC": "LiberationSans-BoldItalic.ttf",
    "FONT_MONO_REGULAR": "LiberationMono-Regular.ttf",
    "FONT_MONO_BOLD": "LiberationMono-Bold.ttf",
}


def font_css(font_dir: Path) -> str:
    """Return CSS with each @font-face url pointing at a font in `font_dir`.

    Forward slashes (as_posix) keep the url valid on Windows too.
    """
    css = CSS
    for placeholder, filename in FONT_FILES.items():
        path = font_dir / filename
        if not path.is_file():
            raise SystemExit(f"missing font: {path}")
        # Quoted, so FONT_BODY_BOLD cannot match inside FONT_BODY_BOLDITALIC.
        css = css.replace(f'"{placeholder}"', f'"{path.as_posix()}"')
    return css


class _WarningGuard(logging.Handler):
    """Collect every xhtml2pdf warning during one render.

    A clean build has none; anything here (missing glyph, unreadable font,
    Helvetica fallback) would otherwise ship as a silently wrong PDF.
    """

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.warnings: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        self.warnings.append((message.splitlines() or [message])[0])


def project_version() -> str:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("version = "):
            return line.split('"')[1]
    return "0.0.0"


def render(name: str, version: str, stamp: str, css: str) -> Path:
    title, subtitle = TITLES[name]
    md = (SRC / f"{name}.md").read_text(encoding="utf-8")
    body = markdown.markdown(
        md, extensions=["tables", "fenced_code", "sane_lists", "attr_list"]
    )
    html = PAGE.format(
        title=title,
        subtitle=subtitle,
        css=css,
        body=body,
        version=version,
        stamp=stamp,
    )
    dest = OUT / f"strata-{name.replace('.', '.')}.pdf"
    guard = _WarningGuard()
    logger = logging.getLogger("xhtml2pdf")
    logger.addHandler(guard)
    buffer = io.BytesIO()
    try:
        # An explicit read root: xhtml2pdf's default derives it from the
        # document path via urlsplit, which reads "C:\\..." as a URL scheme on
        # Windows and falls back to the cwd.
        result = pisa.CreatePDF(
            html,
            dest=buffer,
            encoding="utf-8",
            resource_policy=ResourceAccessPolicy(base_dir=FONT_DIR),
        )
    finally:
        logger.removeHandler(guard)
    if guard.warnings:
        raise SystemExit(f"{name}: " + "; ".join(guard.warnings))
    if result.err:
        raise SystemExit(f"{name}: {result.err} rendering error(s)")
    dest.write_bytes(buffer.getvalue())
    return dest


def main() -> None:
    names = sys.argv[1:] or sorted(TITLES)
    version = project_version()
    stamp = date.today().isoformat()
    css = font_css(FONT_DIR)
    for name in names:
        dest = render(name, version, stamp, css)
        print(f"{dest.relative_to(REPO_ROOT)}  ({dest.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
