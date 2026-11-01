# Cross-platform guide PDFs — design

Date: 2026-11-01 · Size: small change

## Intent

`docs/src/build_pdf.py` only runs on macOS: it reads Arial and Courier New
from `/System/Library/Fonts/Supplemental`. As a result nobody rebuilds the
PDFs — all eight under `docs/` still say v1.24.0 while the code is at 1.34.0,
and CHANGELOG entries keep noting "PDFs not rebuilt, needs the macOS fonts".
Goal: anyone can rebuild the PDFs by hand on Windows, Linux or macOS and get
the same output, with correct Vietnamese.

## Goals / non-goals

- Goal: one command, same result on all three OSes, no network at build time.
- Goal: look unchanged — same layout, same line breaks as the Arial version.
- Non-goal: CI building or checking the PDFs. Rebuilding stays manual
  (decided by the user).
- Non-goal: changing the CSS, page layout, or guide content (guide content is
  a separate follow-up).
- Anti-goal: a PDF that silently drops glyphs (blank boxes for `→` or
  Vietnamese diacritics).

## Approaches

1. **Vendor Liberation Sans/Mono in the repo** — *chosen.* Metric-compatible
   with Arial / Courier New, so layout matches; SIL OFL licence allows
   committing it; ~2.2 MB for six TTFs; no machine or network dependency.
2. Pick system fonts per OS (Arial on Windows/macOS, Liberation on Linux) —
   lighter repo, but each machine needs fonts installed and output may drift
   between OSes.
3. Download fonts at build time — light repo, but first run needs network and
   an external URL that can move.

Evidence for 1 (spike, 2026-11-01, Linux): all eight documents rendered with
Liberation with zero missing-glyph warnings; `architecture.en` paginates to
13 pages exactly like the committed Arial build. Noto Sans lacked `→`;
DejaVu Sans Mono lacked Vietnamese precomposed letters — both rejected.

## Decided

- Fonts live in `docs/src/fonts/`: `LiberationSans-{Regular,Bold,Italic,BoldItalic}.ttf`,
  `LiberationMono-{Regular,Bold}.ttf`, plus the upstream OFL licence file.
  Source: the official liberation-fonts release (2.x).
- `build_pdf.py` reads fonts from that directory via `pathlib`; the macOS
  `FONT_DIR` and the Arial/Courier filename map go away.
- The cover date is the build date (today), not the hard-coded `2026-09-19`.
- Rebuild all eight PDFs with the new script and commit them (they become
  v1.34.0).
- How to rebuild is documented in one place (the script's docstring):
  `uv run --extra docs python docs/src/build_pdf.py [name ...]`, which uses
  the versions pinned in `uv.lock` (xhtml2pdf 0.2.20, reportlab 5.0.1,
  markdown 3.10.3) so pagination matches on every machine;
  `pip install -e ".[docs]"` is the fallback, with newer versions whose line
  breaking may differ. *(Changed during execution: the spike used
  xhtml2pdf 0.2.28 and paginated differently from the locked 0.2.20.)*
- Fonts are not shipped in the wheel or sdist (sdist is `only-include = ["src"]`
  already — verify nothing changes).

## Left to the builder

- Whether the temp-dir font staging (`stage_fonts`) is still needed. It
  existed for space-free names and xhtml2pdf's "inside the document tree"
  rule; Liberation names have no spaces and the fonts sit inside the repo.
  Drop it if xhtml2pdf reads them in place; keep it otherwise.
- Where the two-line "how to rebuild" note goes (module docstring at least).
- A small test that the six font files exist and that rendering a short
  Vietnamese + `→` + code-block sample reports no missing glyphs, if it can
  run without the `docs` extra being mandatory in CI (skip when xhtml2pdf is
  absent).
