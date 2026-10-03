# Receipts

Status: **accept** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED |  | jev+audit | E1, E6 | Added in-memory per-user rate limiter to login() in app/service.py using a module-level dict of deques of monotonic timestamps; purges entries >= 60s old on each call; returns 'rate_limited' when 5 or more attempts remain in the window |
| VERIFIED |  | jev | E2, E6 | Added test_sixth_attempt_is_rate_limited: fails without the rate-limiting change — asserts the 6th login call within 60s returns 'rate_limited' |
| VERIFIED |  | jev | E2, E6 | Added test_fifth_attempt_is_allowed: asserts the 5th attempt is not rate-limited |
| VERIFIED |  | jev | E2, E6 | Added test_rate_limit_is_per_user: asserts exhausting one user's limit does not block a different user |
| VERIFIED |  | jev | E2, E6 | Added test_old_attempts_do_not_count: asserts attempts 61s old are purged and do not count toward the limit |
| VERIFIED |  | jev | E5, E6 | Added test_attempt_exactly_at_window_boundary_expires: asserts attempts exactly 60s old are treated as expired, killing the >= vs > boundary mutant |
| VERIFIED |  | jev | E6 | All 7 tests pass after all changes |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a security team review before they are merged." |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D2: "Password comparison must use a constant-time algorithm (do not use == or != for password comparison)." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D4: "Every behavior change must ship with a test that fails without the change." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D5: "Tests must assert on the specific changed behavior; tests that only exercise the happy path or unrelated behavior do not satisfy the testing requirement." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 3/3 mutants killed
Changed tests on the code before the change: FAIL (good: they check the change)

Last checkpoint: C2 (`refs/hallmonitor/C2`, from E6)

Riskiest changed files: app/service.py (risk 2.53)
