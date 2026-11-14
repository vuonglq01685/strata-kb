# Test review rubric — tester repo

Read by the senior tester review subagent (a separate context from the author).
`docs/test-review-rubric.local.md` is read after this file and wins where the
two disagree.

Severity ladder, used by every review in the flow:

| Level | Meaning |
|---|---|
| **BLOCKER** | A wrong verdict, an uncovered acceptance criterion, a leaked secret, or a test that can damage a shared environment. No approval while one stands. |
| **SUGGESTED** | Should be fixed now: a weak technique choice, a fragile script, a thin assertion. |
| **NOTE** | Worth improving later. Record it; do not block. |
| **NITS** | Naming, formatting, wording. |

Convergence: round 1 is exhaustive; round 2 verifies only the round-1 items,
regressions of the fix, and any BLOCKER. Pass when no BLOCKER and at most two
SUGGESTED remain; carried SUGGESTED rows go to `## Review record`. Still a
BLOCKER after round 2: stop for a human.

## Q1 axes

Used after the test cases and scripts are written, before the run.

- [ ] Every acceptance criterion of the story is covered by at least one test
      case, and each test case matches the intent of its AC. **BLOCKER**
- [ ] Each test case uses a technique that fits it (equivalence partitioning,
      boundary value, decision table, state transition, use case). **SUGGESTED**
- [ ] Negative, boundary and alternate/exception flows are covered where the
      ticket states a value, limit, format, state or flow. **BLOCKER**
- [ ] Each test case names exactly one existing script, and no script is
      orphaned. **BLOCKER**
- [ ] Scripts follow the repo's script rules: no fixed sleeps, stable
      locators, one assertion target per expected result, login through the
      shared fixture. **SUGGESTED**
- [ ] Test data is isolated: each test case creates or seeds what it needs and
      does not depend on another case's leftovers. **BLOCKER**
- [ ] Seed and reset scripts touch only `$<url_env>` and never a protected
      environment. **BLOCKER**

## Q2 axes

Used after the run, before the report PR.

- [ ] The verdict follows the evidence: any failing story test case gives
      `FAIL`, otherwise `PASS`. **BLOCKER**
- [ ] Every defect was reproduced through Playwright MCP and assigned to the
      right child ticket of the story. **BLOCKER**
- [ ] Every regression defect is confirmed against a `closed` story's
      baseline, with its broken TC and overlap named. **BLOCKER**
- [ ] A flaky test is handled by the repo's flaky-test rules (retries, then a
      note), never silently turned into a pass. **BLOCKER**
- [ ] No secret, credential or environment variable value appears in the
      report, evidence or logs. **BLOCKER**
- [ ] Evidence images exist, are PNG or WebP, and show what the row claims.
      **SUGGESTED**

## Report format

A review returns a table and a verdict line, nothing else:

| Severity | File | Line | Why it is wrong | Fix |
|---|---|---|---|---|
| BLOCKER | `tests/US-12/test-cases.md` | 40 | … | … |

Blocking: No

The verdict line sits at column zero, exactly as shown — `Blocking: Yes`
while any BLOCKER stands, `Blocking: No` otherwise.
