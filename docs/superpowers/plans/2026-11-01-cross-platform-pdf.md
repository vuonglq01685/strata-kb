# Cross-platform guide PDFs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `python docs/src/build_pdf.py` produces the same guide PDFs on Windows, Linux and macOS.

**Architecture:** Vendor Liberation Sans/Mono 2.1.5 (SIL OFL 1.1) under `docs/src/fonts/`; `build_pdf.py` reads them from there instead of macOS's Supplemental directory, fails on any missing-glyph warning, and stamps the build date. Then rebuild and commit all eight PDFs.

**Tech Stack:** Python 3, xhtml2pdf + markdown (`docs` extra), pytest.

**Spec:** `docs/superpowers/specs/2026-11-01-cross-platform-pdf-design.md`

## Global Constraints

- Fonts: `LiberationSans-{Regular,Bold,Italic,BoldItalic}.ttf`, `LiberationMono-{Regular,Bold}.ttf`, version 2.1.5, plus `docs/src/fonts/LICENSE` (OFL 1.1 text with the Liberation copyright lines).
- No network at build time; no OS-specific paths; paths via `pathlib`.
- Cover date = build date (`date.today().isoformat()`), not `2026-09-19`.
- CSS, page layout, guide content unchanged.
- Wheel/sdist unchanged (sdist is `only-include = ["src"]`).
- No version bump: this is docs tooling, the PDFs are stamped with the current 1.34.0.

## Review Focus

- A glyph none of the fonts has (e.g. an emoji added to a guide later) → build must fail naming the character, not write a PDF with a blank box. Test: `test_render_fails_on_missing_glyph`.
- Building from a working directory other than the repo root (e.g. `cd docs/src`) → fonts still found. Covered by resolving the font dir from `__file__`; test renders with cwd = `tmp_path`.
- A font file missing from `docs/src/fonts/` → clear `SystemExit("missing font: ...")`, as today. Test: `test_vendored_fonts_present` guards the repo state.
- `docs` extra not installed (CI's default env) → the font-presence test still runs; render tests skip via `pytest.importorskip("xhtml2pdf")`.
- Windows path separators inside the CSS `url("...")` → use `Path.as_uri()` or forward slashes (`as_posix()`), never a raw `str(Path)`.

---

### Task 1: Vendor fonts and make `build_pdf.py` OS-independent

**Files:**
- Create: `docs/src/fonts/LiberationSans-Regular.ttf`, `-Bold.ttf`, `-Italic.ttf`, `-BoldItalic.ttf`, `docs/src/fonts/LiberationMono-Regular.ttf`, `-Bold.ttf`, `docs/src/fonts/LICENSE`
- Modify: `docs/src/build_pdf.py`
- Test: `tests/test_build_pdf.py`

**Interfaces:**
- Produces: `build_pdf.FONT_DIR: Path` (= `SRC / "fonts"`), `build_pdf.font_css(font_dir: Path) -> str` (CSS with `@font-face` urls filled), `build_pdf.render(name, version, stamp, css) -> Path` (unchanged signature; raises `SystemExit` on a missing glyph), `build_pdf.main()` (stamp = today).

- [ ] **Step 1: Copy fonts + licence.** Source: Liberation 2.1.5 TTFs (Debian `fonts-liberation 1:2.1.5-3` ships upstream binaries unmodified). LICENSE = copyright lines + OFL 1.1 text.

- [ ] **Step 2: Write failing tests** in `tests/test_build_pdf.py`, loading the script with `importlib.util.spec_from_file_location("build_pdf", REPO_ROOT / "docs/src/build_pdf.py")`:
  - `test_vendored_fonts_present` (no deps): the six TTFs and `LICENSE` exist under `docs/src/fonts/`; LICENSE contains `"SIL OPEN FONT LICENSE Version 1.1"`.
  - `test_render_vietnamese_sample_has_no_missing_glyphs` (importorskip xhtml2pdf, markdown): monkeypatch `SRC`/`OUT` to `tmp_path`, write `sample.vi.md` with `"Tiếng Việt: ể ả ầ ề ố ế ổ → \`mã ể ả\`"` plus a fenced block containing `ể`, add `TITLES["sample.vi"]`, `chdir(tmp_path)`, render with `font_css(FONT_DIR)`; assert PDF exists and starts with `b"%PDF"`.
  - `test_render_fails_on_missing_glyph`: same setup, body contains `"🙂"`; `pytest.raises(SystemExit, match="U\\+1F642")`.
  - `test_font_dir_is_inside_repo`: `FONT_DIR == REPO_ROOT / "docs/src/fonts"`.

- [ ] **Step 3: Run** `uv run --extra docs pytest tests/test_build_pdf.py -v` → FAIL (no `font_css`, fonts absent).

- [ ] **Step 4: Implement.** `FONT_DIR = SRC / "fonts"`; replace `STAGED`/`stage_fonts` with a mapping of CSS alias → Liberation filename and `font_css(font_dir)` that checks each file exists (`SystemExit(f"missing font: {path}")`) and fills `url()` with `path.as_posix()`. Drop the temp-dir staging if xhtml2pdf reads the fonts in place (verify by running from `tmp_path` cwd); keep it otherwise. In `render`, attach a `logging.Handler` to `logging.getLogger("xhtml2pdf")` for the call, collect records whose message starts with `"No font this document has can draw"`, and raise `SystemExit(f"{name}: " + "; ".join(...))` if any. `main()` stamps `date.today().isoformat()`. Docstring: replace the macOS sentence with the two-line rebuild recipe `pip install -e ".[docs]"` / `python docs/src/build_pdf.py [name ...]` and a note that fonts are vendored Liberation (OFL).

- [ ] **Step 5: Run** the tests → PASS; also `uv run pytest tests/test_build_pdf.py -v` without the extra → font test passes, render tests SKIPPED.

- [ ] **Step 6: Lint/type** `uv run ruff check tests/test_build_pdf.py docs/src/build_pdf.py && uv run ruff format --check tests/test_build_pdf.py docs/src/build_pdf.py`.

- [ ] **Step 7: Commit** `fix(docs): build guide PDFs on any OS with vendored Liberation fonts`.

### Task 2: Rebuild the eight PDFs

**Files:**
- Modify: `docs/strata-{architecture,guide-ba,guide-dev,guide-hub-child}.{en,vi}.pdf`
- Modify: `CHANGELOG.md` lines 16 and 27 are historical — leave them.

- [ ] **Step 1: Run** `uv run --extra docs python docs/src/build_pdf.py` → eight lines, no error.
- [ ] **Step 2: Verify** each PDF's first page text contains `strata-kb v1.34.0` (pypdf), and spot-render one VI page to PNG to eyeball diacritics, `→`, code and tables.
- [ ] **Step 3: Verify packaging unaffected:** `uv run pytest tests/test_check_package.py tests/test_readme.py -q` → pass.
- [ ] **Step 4: Commit** `docs: rebuild guide PDFs for 1.34.0`.
