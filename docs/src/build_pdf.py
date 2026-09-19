#!/usr/bin/env python3
"""Render the Markdown sources in this directory to PDFs in docs/.

Usage:  python docs/src/build_pdf.py [name ...]

Fonts come from macOS's Supplemental directory because they carry the full
Vietnamese diacritic set; ReportLab's built-in Helvetica does not.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import markdown
from xhtml2pdf import pisa

SRC = Path(__file__).resolve().parent
OUT = SRC.parent
REPO_ROOT = OUT.parent
FONT_DIR = Path("/System/Library/Fonts/Supplemental")

TITLES = {
    "architecture.en": ("Strata — Architecture", "Knowledge Base as Code"),
    "architecture.vi": ("Strata — Kiến trúc hệ thống", "Knowledge Base as Code"),
    "guide-hub-child.en": ("Strata — Hub & Child Guide", "For knowledge owners and authors"),
    "guide-hub-child.vi": ("Strata — Hướng dẫn Hub & Child", "Dành cho người quản trị và biên soạn tri thức"),
    "guide-ba.en": ("Strata — BA Guide", "For business analysts"),
    "guide-ba.vi": ("Strata — Hướng dẫn BA", "Dành cho Business Analyst"),
    "guide-dev.en": ("Strata — Developer Guide", "For engineers implementing tickets"),
    "guide-dev.vi": ("Strata — Hướng dẫn Developer", "Dành cho kỹ sư triển khai ticket"),
}

CSS = """
@page {
  size: a4 portrait;
  margin: 20mm 18mm 18mm 18mm;
  @frame footer { -pdf-frame-content: footer; bottom: 9mm; left: 18mm; right: 18mm; height: 8mm; }
}

@font-face { font-family: Body; src: url("FONTS/body-regular.ttf"); }
@font-face { font-family: Body; src: url("FONTS/body-bold.ttf"); font-weight: bold; }
@font-face { font-family: Body; src: url("FONTS/body-italic.ttf"); font-style: italic; }
@font-face { font-family: Body; src: url("FONTS/body-bolditalic.ttf"); font-weight: bold; font-style: italic; }
@font-face { font-family: Mono; src: url("FONTS/mono-regular.ttf"); }
@font-face { font-family: Mono; src: url("FONTS/mono-bold.ttf"); font-weight: bold; }

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


STAGED = {
    "body-regular.ttf": "Arial.ttf",
    "body-bold.ttf": "Arial Bold.ttf",
    "body-italic.ttf": "Arial Italic.ttf",
    "body-bolditalic.ttf": "Arial Bold Italic.ttf",
    "mono-regular.ttf": "Courier New.ttf",
    "mono-bold.ttf": "Courier New Bold.ttf",
}


def stage_fonts(target: Path) -> Path:
    """Copy the Vietnamese-capable system fonts under space-free names.

    xhtml2pdf refuses to read anything outside the document's own directory
    tree, so the fonts are copied under space-free names into a temporary
    directory inside the repository. Nothing is committed: the directory is
    removed when the build finishes.
    """
    target.mkdir(parents=True, exist_ok=True)
    for alias, filename in STAGED.items():
        source = FONT_DIR / filename
        if not source.is_file():
            raise SystemExit(f"missing font: {source}")
        shutil.copyfile(source, target / alias)
    return target


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
        title=title, subtitle=subtitle, css=css, body=body,
        version=version, stamp=stamp,
    )
    dest = OUT / f"strata-{name.replace('.', '.')}.pdf"
    with dest.open("wb") as fh:
        result = pisa.CreatePDF(html, dest=fh, encoding="utf-8")
    if result.err:
        raise SystemExit(f"{name}: {result.err} rendering error(s)")
    return dest


def main() -> None:
    names = sys.argv[1:] or sorted(TITLES)
    version = project_version()
    stamp = "2026-09-19"
    with tempfile.TemporaryDirectory(prefix=".strata-fonts-", dir=REPO_ROOT) as tmp:
        css = CSS.replace("FONTS", str(stage_fonts(Path(tmp))))
        for name in names:
            dest = render(name, version, stamp, css)
            print(f"{dest.relative_to(REPO_ROOT)}  ({dest.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
