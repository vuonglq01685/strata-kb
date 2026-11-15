# Test strategy — <product>
> Revision: 1
> Plan: <ba-repo-id>

## Scope & objectives
<!-- What is tested, what is not, and what this strategy is for.
Images go in docs/assets/ (png/webp): `![caption](assets/<file>.png)`. -->

## Test levels & types
<!-- One row per test type this repo runs. -->
| Type | In scope | Tool | Runs on | Notes |
|---|---|---|---|---|
| UI | yes | <tool> | <env> | |
| API | yes | <tool> | <env> | |

## Priority order
<!-- Rank: 1 = test first, ties allowed, `last` = deliberately at the end.
Target: a mission `M-<slug>`, a story `M-<slug>-US<n>`, or a KB area
`[<repo:doc-id> §<section>]`. Pin: `rev <N>` for a mission/story, `—` for a
KB area. Risk: High | Medium | Low. A target appears in at most one row. -->
| Rank | Target | Pin | Risk | Why | Types |
|---|---|---|---|---|---|
| 1 | M-checkout | rev 3 | High | payment path, money | UI, API |
| 1 | [acme:srs §4.2] | — | High | refunds, no mission yet | API |
| last | M-checkout-US5 | rev 2 | Low | static page | UI |

## Rounds
<!-- Optional: waves of ranks, and entry/exit per wave. Delete if unused. -->

## Environments & data
<!-- Point at .kb/test-env.yaml; no secrets here. -->

## Entry & exit criteria
<!-- When testing of a story may start, and when it is done. -->

## Regression policy
<!-- What is re-run, when, and who decides. -->

## Risks & mitigations
<!-- Product and schedule risks that shape the order above. -->

## Open questions
<!-- Every open point has an owner. -->
- [ ] Q1 — <question> — owner: <who> — blocks: <row or section>

## KB context
```yaml
kb-context:
  version: "<hub commit>"
  refs:
    - <repo:doc-id> §<section>
  tags: [ … ]
```

## Change log
<!-- Append-only: one row per revision >= 2; bump `> Revision:` in the same
edit. Trigger is one or more of kb-context, plan, coverage, priority, scope
(comma-separated). Affected is section names, or `-`. -->
| Rev | Date | Trigger | What changed | Affected | Review |
|---|---|---|---|---|---|
|   |   |   |   |   |   |

## Review record
<!-- One row per review round; keep the history. -->
| Date | Round | Verdict | Reviewer |
|---|---|---|---|
