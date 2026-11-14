# R1 — ST-1 — Show airspace
> Story: ST-1 · Round: 1 · Verdict: FAIL
> Environment: staging · shop-fe abc1234 · shop-api def5678 · Date: 2026-11-14
> Test cases: tests/ST-1/test-cases.md @ 1a2b3c4

## Summary
3/3 TCs passed, 1 defect, 1 regression defect

## Results by AC
| AC | TC | Result | Script | Evidence |
|---|---|---|---|---|
| AC1 | TC-01 | PASS | tests/ST-1/tc01.spec.ts | ![](assets/tc01.png) |
| AC2 | TC-02 | PASS | tests/ST-1/tc02.spec.ts | |
| AC2 | TC-03 | PASS | tests/ST-1/tc03.spec.ts | |

## Defects
### D1 — airspace filter lost   Guilty: ST-1.web · Regression: yes · S2 · P1
Broken TC: ST-0 TC-3 · Baseline: R1 @ abc1234 passed
Overlap: /airspace ↔ filter.ts in PR 4
Steps to reproduce: open the airspace list, apply a filter
Expected: the filter narrows the list
Actual: the list is unchanged
Evidence: assets/tc01.png
Environment: staging

## Regression
Run: yes
Failed: ST-0/TC-3, ST-0/TC-4
Known: ST-0/TC-5
Suite of 6 TCs, 3 passed, 2 failed, 1 known.

## Regression defects
### RD1 — export button missing   Story: ST-0 · TC-4 · S3 · P2
Steps to reproduce: open the export menu
Expected: the export button shows
Actual: the menu is empty
Evidence: assets/tc01.png
Environment: staging

## Environment & data seeds
staging, seed a.

## Review record
| Date | Round | Verdict | Reviewer | Coverage | Open gaps |
|---|---|---|---|---|---|
| 2026-11-14 | 2 | pass | senior-tester | complete | none |
