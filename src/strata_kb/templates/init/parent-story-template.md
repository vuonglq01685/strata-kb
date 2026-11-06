# <Title — one line, imperative, with identifier>
> Kind: parent story
> Revision: 1
<!-- A parent story is the business story split across repos. It has NO
`## Acceptance Criteria` and NO `## Definition of Ready`: every AC lives in
exactly one child ticket (`<parent-id>.<repo-id>`, a later child for the same
repo `<parent-id>.<repo-id>.<n>`, n >= 2). Each child carries
`> Parent story: <parent-id> @ rev <N>` and `> Target repo: <repo-id>`, and
repeats this `## User Story` word for word. -->

## User Story
As a <role>, I want <capability>, so that <value>.

## Split
<!-- One row per child ticket, columns exactly as below.
Child: the child ticket id. Repo: its target repo id.
AC: the AC ids the child owns, e.g. `AC1, AC2`. An AC that replaces one in a
finished child is written `AC7 (replaces AC2)`; the old AC may stay there.
Blocked by: child ids from this table, comma-separated, or `-`. No cycles.
Own fix: what the repo's own team fixes or adds, or `-`.
Why: why this slice belongs to this repo. -->
| Child | Repo | AC | Blocked by | Own fix | Why |
|---|---|---|---|---|---|
| <parent-id>.<repo-id> | <repo-id> | AC1, AC2 | - | - | <why> |

## Change log
<!-- Append-only: one row per revision >= 2, in order; bump `> Revision:` under
the title in the same edit. Trigger is one or more of kb-context,
architecture, scope, delivery, question (comma-separated). Affected is the
child ids, or `-`. -->
| Rev | Date | Trigger | What changed | Affected | Review |
|---|---|---|---|---|---|
|   |   |   |   |   |   |
