# TDD exemptions — the only changes that may ship without a red test first

The rule this document bounds, from every dev skill's hard rules:

> No production code without a failing test observed first. No exception for
> small tickets, deadlines, or "obvious" changes.

That rule is absolute. This document does not carve holes in it; it defines
what counts as production code.

**The boundary.** An exemption is a property of a **change class with no
observable behaviour** — never of a ticket's size, a deadline, or how obvious
the change looks. The moment a change alters behaviour an acceptance criterion
can see, no exemption applies, whatever the file extension.

**When it is decided.** An exemption is declared **when the plan is written**,
as one line inside the task block:

    Exempt: <config|ci|docs|style> — verified by <what>

It is never a decision taken mid-implementation. An implementer holding a task
with no `Exempt:` line who believes no test is possible **stops and returns the
task to `dev-plan`** — the same route an unimplementable AC takes. Deciding it
alone, with the code half-written, is the failure this document exists to
prevent.

**The four categories.** The slug is one of exactly these; a change that fits
none of them is not exempt.

| Slug | Covers | What you owe instead |
|---|---|---|
| `config` | config files, dependency bumps, scaffold changes | run the thing you just configured and paste the output — the build, `kb doctor`, the service starting |
| `ci` | workflow, job and gate definitions | that workflow's own run on this PR: link and status |
| `docs` | README, QUICKSTART, prose, skill text | paste the diff and any link/render check |
| `style` | formatting, renames, file moves with no behaviour change | the existing suite green **before and after**, plus the command showing behaviour is unchanged |

**`docs` is not an extension whitelist.** Where a repo pins document content
with a test — canon tests over template text, snapshot tests over generated
docs — a documentation change still owes a test, and is not exempt. The
question is always *"is there a test that can observe this?"*, never *"what is
this file's extension?"*.

Every exemption taken during a ticket is reported in the PR description under
`## TDD exemptions`, one line each, copied from the plan. The CI gate
(`kb pr lint`) requires that section to read `none`, or hold one line per
exemption naming one of `config`, `ci`, `docs`, `style`; write `none` when
every task was test-first.
