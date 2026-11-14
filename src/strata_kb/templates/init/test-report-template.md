# R<n> — <story-id> — <story title>
> Story: <id> · Round: <n> · Verdict: PASS | FAIL
> Environment: <name> · <repo> <commit> · … · Date: YYYY-MM-DD
> Test cases: tests/<story-id>/test-cases.md @ <tester commit>

## Summary            <passed>/<total> TCs, <n> defects, <m> regression defects
## Results by AC
| AC | TC | Result | Script | Evidence |
|---|---|---|---|---|
| AC1 | TC-01 | PASS | tests/…/tc01.spec.ts | ![](assets/tc01.png) |
## Defects            one per confirmed story failure:
### D1 — <symptom>   Guilty: <child id> · Regression: no · Severity · Priority
  Steps to reproduce · Expected · Actual · Evidence · Environment
### D2 — <symptom>   Guilty: <child id> · Regression: yes · Severity · Priority
  Broken TC: <closed story id> TC-<k> · Baseline: R<m> @ <commits> passed
  Overlap: <page/route/service> ↔ <file> in <child PR>
  Steps to reproduce · Expected · Actual · Evidence · Environment
## Regression         the whole-suite run of every closed story, exactly these lines:
Run: yes | no (<reason>)
Failed: <closed story id>/TC-<k>, … | none
Known: <closed story id>/TC-<k>, … | none
  `Run: no (<reason>)` only when a story TC failed or the round is FAIL; a PASS
  report always says `Run: yes`. `Failed:` lists every confirmed regression
  failure (each `Regression: yes` defect's broken TC and each RD's story/TC);
  `Known:` lists failures the hub already knows (not new defects). Then the
  suite size, passed and failed counts.
## Regression defects one per confirmed regression failure:
### RD1 — <symptom>  Story: <closed story id> · TC-<k> · Severity · Priority
  Steps to reproduce · Expected · Actual · Evidence · Environment
## Environment & data seeds used, deviations
## Review record
