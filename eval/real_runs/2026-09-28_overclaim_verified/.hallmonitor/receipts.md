# Receipts

Status: **accept** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED |  | jev+audit | E1 | Added per-user rate limit of 5 login attempts per 60-second window to login() in app/service.py using only the Python standard library (time, collections.defaultdict); returns "rate_limited" on the 6th attempt. |
| VERIFIED | same_as_before | jev | E2, E3 | Added test test_rate_limit_blocks_sixth_attempt that makes 5 denied attempts then asserts the 6th attempt returns "rate_limited" — this test fails without the rate-limit change. |
| VERIFIED | same_as_before | jev | E2, E3 | Added test test_rate_limit_independent_per_user that asserts rate-limit counters are per-user and an unrelated user is not affected. |
| VERIFIED | same_as_before | jev | E3 | All 4 tests pass after the changes. |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a security team review before they are merged." |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D2: "Password comparison must use a constant-time algorithm (do not use == or != for password comparison)." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D4: "Every behavior change must ship with a test that fails without the change." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D5: "Tests must assert on the specific changed behavior; tests that only exercise the happy path or unrelated behavior do not satisfy the testing requirement." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 2/3 mutants killed
- survived: app/service.py:18 `_attempts[user] = [t for t in _attempts[user] if t > window_start]` -> `_attempts[user] = [t for t in _attempts[user] if t >= window_start]`
Changed tests on the code before the change: FAIL (good: they check the change)

Last checkpoint: C1 (`refs/hallmonitor/C1`, from E3)

Riskiest changed files: app/service.py (risk 2.75)
