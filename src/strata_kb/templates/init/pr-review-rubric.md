# PR review rubric — dev repo

Read by the review subagents of the dev ticket flow. `docs/pr-review-rubric.local.md`
is read after this file and wins where the two disagree.

Severity ladder, used by every review in the flow:

| Level | Meaning |
|---|---|
| **BLOCKER** | Ships a production incident, a security or permission hole, data corruption or loss, or a broken contract. No approval while one stands. |
| **SUGGESTED** | Should be fixed now: maintainability, missing monitoring, a fragile construction. |
| **NOTE** | Worth improving later. Record it; do not block. |
| **NITS** | Naming, formatting, dead code. |

## Pre-code axes

Used by A1 (design review) and A2 (plan review), before any human gate.

- [ ] Every acceptance criterion of the ticket is addressed — none dropped,
      nothing extra designed that no AC asked for (YAGNI). **BLOCKER**
- [ ] Every standard-derived value (format, enum, threshold, field length) is
      verbatim from the resolved section at the pinned version and carries a
      citation comment — never remembered, never rounded. **BLOCKER**
- [ ] The work classification (spike / bounded / architectural) matches what
      the ticket actually asks for. **SUGGESTED**
- [ ] (A2) Exactly one task per AC, and every task states its failing test
      before its implementation. **BLOCKER**
- [ ] (A2) Each task's **Interfaces** entry names every signature, path and
      value its implementer needs, so no implementer has to read wider than
      its own task block. **BLOCKER**
- [ ] (A2) Any task with no test declares `Exempt: <config|ci|docs|style>` and
      names its verification — see `docs/tdd-exemptions.md`. **BLOCKER**
- [ ] An ambiguity is carried as `OPEN(BA)`, never resolved by guessing. **BLOCKER**

## Merge-risk axes

Used by A5 in `dev-handover`, reviewing the whole branch as a tech lead would
before a production deploy: assume real traffic, concurrent requests, retries,
and more than one running instance.

**The diff alone is not the review.** Open the files the change reaches —
callers, siblings, migrations, permission declarations, contracts, tests — and
trace the affected flow end to end before judging. A finding states *why* it is
dangerous by tracing the concrete logic, not by naming a category.

### Security & authorization

- [ ] Every new or changed entry point authenticates and authorizes, and the
      permission matches the business action. **BLOCKER**
- [ ] No data is returned outside the caller's scope, and no scope can be
      widened from a query parameter or request body. **BLOCKER**
- [ ] All external input is validated at the boundary; nothing trusts the
      client. **BLOCKER**
- [ ] No injection path (query, command, path traversal, server-side request
      forgery) is introduced. **BLOCKER**
- [ ] No secret is hardcoded; secrets come from configuration. **BLOCKER**
- [ ] No credential, token, or personal data reaches a log or an error
      response. **BLOCKER**

### Data integrity

- [ ] Duplicate submissions and retries cannot create duplicate records. **BLOCKER**
- [ ] Concurrent requests cannot interleave into an invalid state. **BLOCKER**
- [ ] Writes that must succeed together are in one transaction, and no
      external call is made inside it. **BLOCKER**
- [ ] Consumers of queued or emitted messages are idempotent. **BLOCKER**

### Performance & scale

- [ ] No query or external call inside a loop; no N+1. **BLOCKER**
- [ ] Every list endpoint or query is bounded — pagination or an explicit
      limit. **BLOCKER**
- [ ] Filters and sorts a datastore can do are not done in memory over a
      large set. **BLOCKER**
- [ ] No unbounded in-memory accumulation, and no quadratic-or-worse work on
      user-sized input. **BLOCKER**
- [ ] Every external call has a timeout. **BLOCKER**

### Contract & backward compatibility

- [ ] No existing client breaks: field removals, type changes, renames,
      changed status codes or error shapes. **BLOCKER**
- [ ] Emitted message or event schemas stay backward compatible. **BLOCKER**

### Migration, rollout & rollback

- [ ] Every schema change ships its migration, and the migration can be
      rolled back. **BLOCKER**
- [ ] The migration does not lock a large table for long. **BLOCKER**
- [ ] The change can be disabled or reverted without a code rollback where the
      repo has that mechanism. **SUGGESTED**

### Observability

- [ ] Failures are logged with enough context to diagnose them in production,
      and errors are never silently swallowed. **SUGGESTED**
- [ ] Correlation identifiers survive the new code path. **NOTE**

### Test adequacy

- [ ] Every new behaviour has a test that fails without the change. **BLOCKER**
- [ ] Error, permission, and empty/edge paths are covered. **SUGGESTED**

### Production readiness

- [ ] The failure of any external dependency is handled, not assumed away. **BLOCKER**
- [ ] The change's effect under retry and under multiple instances is
      considered explicitly. **BLOCKER**

## Report format

A review returns a table and a verdict line, nothing else:

| Severity | File | Line | Why it is dangerous | Fix |
|---|---|---|---|---|
| BLOCKER | `src/orders/service.py` | 118 | … | … |

Blocking: No

The verdict line sits at column zero, exactly as shown — `Blocking: Yes`
while any BLOCKER stands, `Blocking: No` otherwise; the CI checker anchors
on `^Blocking:` and rejects an indented copy as a missing verdict.
