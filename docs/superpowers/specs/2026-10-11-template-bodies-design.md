# One template body per skill

**Status:** approved design (decisions taken 2026-10-11)
**Source:** §4.2 ("Template nhân ba bằng tay") and §8 đợt 3 item 9 of
`docs/superpowers/reviews/2026-10-10-full-framework-review.vi.md`. This is
batch 3d of wave 3. It follows #86, #87 and #88 (3a–3c).
**Scope**, as chosen on 2026-10-11:
- Copilot and Cursor share one body per skill.
- So does the Claude skill, wherever its copy differs only in its
  heading or intro.
- Claude skills that genuinely differ stay separate. They orchestrate
  subagents, which Copilot and Cursor cannot.

## Goal

Thirteen skills ship two or three hand-kept copies of the same body:

- `copilot-<skill>.prompt.md` and `cursor-<skill>.md` are identical after
  their frontmatter.
- For seven of those skills, `claude-skill-<skill>.md` is too, apart from
  its heading or an intro paragraph.

An edit to one copy has to be repeated in the others by hand, and tests
exist to catch the copies drifting.

## Design

- **Bodies.** `templates/init/bodies/<skill>.md` holds the text a skill's
  copies share: the longest common tail after their frontmatter.
- **Stubs.** Each copy keeps its file name. Its content is reduced to:
  1. its own frontmatter;
  2. whatever genuinely differs per tool (a heading, and for some skills
     an intro paragraph);
  3. one final line, `<!-- strata-kb:include bodies/<skill>.md -->`.
- **Rendering.** `initcmd.read_template(name)` returns the stub with
  that last line replaced by the body. `kb init` and every other reader
  of a template go through it.
- **Output unchanged.** Every file `kb init` writes is byte-identical to
  1.15.1. This was checked once against a sha256 snapshot of all 168
  templates taken before the change.

| Skill | Shares a body |
|---|---|
| ba-mission-plan, dev-code-seed, dev-design, dev-execute, dev-handover, dev-plan, sa-ticket-ground | Claude skill + Copilot + Cursor |
| ba-ticket-author, dev-implement-ticket, kb-approve, kb-docker-setup, kb-init, kb-mcp-setup | Copilot + Cursor |
| kb-ingest, kb-publish, kb-summarize | none: the common part is under 20 lines, or none at all |

## Out of scope

- Merging the Claude-only orchestration text into the shared body with
  conditional blocks. That needs template syntax and real content edits.
- `claude-command-*` wrappers. They are short and different by design.

## Testing

- `tests/test_template_bodies.py`:
  - every body is referenced by at least two stubs, and none is orphaned;
  - a stub is frontmatter, a short intro of its own and the directive;
  - no rendered template, and no file `kb init` writes for any kind,
    carries a directive;
  - every stub renders to its own prefix followed by the shared body.
- **Existing tests.** The template tests read through `read_template`,
  and the content tests still pass for every copy.
- **Sync tests.** The cross-copy byte-identity tests are kept. Most of
  them also compare files that are not merged, such as `claude-command`
  wrappers and other skills, so they still guard something. The review's
  "3,054 lines of sync tests" is the whole `test_templates.py`, which is
  mostly per-skill content assertions, so it stays.

## Delivery

One PR, release **1.15.2**. Packaging changes only: what `kb init`
writes is unchanged.
