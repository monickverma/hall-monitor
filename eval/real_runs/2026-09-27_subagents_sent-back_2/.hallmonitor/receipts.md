# Receipts

Status: **needs_evidence** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| NEEDS EVIDENCE | uncited | code |  | The audit confirms the surviving mutant is a **docstring-only change** that no behavioral test can kill. |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a security team review before they are merged." |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D2: "Password comparison must use a constant-time algorithm (do not use == or != for password comparison)." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D4: "Every behavior change must ship with a test that fails without the change." |
| CAN'T CHECK |  | jev_deep |  | The finished work satisfies the project rule D5: "Tests must assert on the specific changed behavior; tests that only exercise the happy path or unrelated behavior do not satisfy the testing requirement." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 3/4 mutants killed
- survived: app/ratelimit.py:14 `Return False if under the limit, recording the current attempt.` -> `Return True if under the limit, recording the current attempt.`
Changed tests on the code before the change: FAIL (good: they check the change)

Last checkpoint: C3 (`refs/hallmonitor/C3`, from E12)

Riskiest changed files: app/service.py (risk 2.7), app/ratelimit.py (risk 2.51)
