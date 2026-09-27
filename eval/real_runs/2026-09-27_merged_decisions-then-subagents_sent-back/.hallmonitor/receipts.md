# Receipts

Status: **send_back** (send-backs so far: 1)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED | code | code |  | This is the standard test command specified in [`AGENTS.md`](AGENTS.md) (`python -m pytest -q`) and does not add any new dependency to the service — pytest is already installed and in use. |
| NEEDS EVIDENCE | uncited | code |  | *[`app/ratelimit.py`](app/ratelimit.py)** — new file, in-memory limiter, stdlib only |
| NEEDS EVIDENCE | uncited | code |  | *[`app/service.py`](app/service.py)** — calls `check_rate_limit(user)` before `check_password` |
| NEEDS EVIDENCE | uncited | code |  | *[`tests/test_service.py`](tests/test_service.py)** — two new tests: 5th attempt allowed, 6th blocked |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a review by the security team before they are merged." |
| NEEDS EVIDENCE |  | jev |  | The finished work satisfies the project rule D2: "Password comparison must remain constant-time." |
| VERIFIED |  | jev_deep |  | The finished work satisfies the project rule D4: "New third-party dependencies require written approval from Platform Security before being added." |
| NEEDS EVIDENCE |  | jev_deep |  | The finished work satisfies the project rule D5: "Every behavior change must ship with a test that fails without the change." |
| CAN'T CHECK |  | jev_deep |  | The finished work satisfies the project rule D6: "Tests that do not assert on the changed behavior do not count toward the testing requirement." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 3/4 mutants killed
- survived: app/ratelimit.py:23 `timestamps[:] = [t for t in timestamps if t > cutoff]` -> `timestamps[:] = [t for t in timestamps if t >= cutoff]`
Changed tests on the code before the change: FAIL (good: they check the change)

Riskiest changed files: app/service.py (risk 2.65), app/ratelimit.py (risk 2.63)
