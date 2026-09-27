# Receipts

Status: **stuck** (send-backs so far: 4)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED |  | jev | E3 | Created app/ratelimit.py with a RateLimiter class using only stdlib (collections.deque + time.time) that allows 5 attempts per user per 60-second sliding window and raises RateLimitExceeded on the 6th attempt |
| VERIFIED |  | jev | E4 | Wired the rate limiter into app/service.py so login() returns 'rate_limited' when RateLimitExceeded is raised |
| VERIFIED |  | jev | E5, E6 | Added test_first_five_attempts_not_rate_limited to tests/test_service.py asserting the first 5 attempts are not rate-limited using monkeypatched time |
| VERIFIED |  | jev | E5, E6 | Added test_sixth_attempt_is_rate_limited to tests/test_service.py asserting RateLimitExceeded is raised on the 6th attempt within the window using monkeypatched time |
| VERIFIED |  | jev | E5, E6 | Added test_login_returns_rate_limited_on_sixth_attempt to tests/test_service.py asserting login() returns 'rate_limited' on the 6th call within the window |
| CAN'T CHECK |  | jev_deep | E5, E6 | Added test_rate_limit_resets_after_window asserting attempts are allowed again after the 60-second window expires |
| CAN'T CHECK |  | jev_deep | E6 | All 6 tests pass (2 pre-existing + 4 new rate-limit tests) with no third-party dependencies |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a security team review before they are merged." |
| NEEDS EVIDENCE |  | jev |  | The finished work satisfies the project rule D2: "Password comparison must use a constant-time algorithm (do not use == or != for password comparison)." |
| NEEDS EVIDENCE |  | jev_deep |  | The finished work satisfies the project rule D4: "Every behavior change must ship with a test that fails without the change." |
| NEEDS EVIDENCE |  | jev_deep |  | The finished work satisfies the project rule D5: "Tests must assert on the specific changed behavior; tests that only exercise the happy path or unrelated behavior do not satisfy the testing requirement." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 2/3 mutants killed
- survived: app/ratelimit.py:29 `while bucket and bucket[0] <= cutoff:` -> `while bucket and bucket[0] < cutoff:`
Changed tests on the code before the change: FAIL (good: they check the change)

Last checkpoint: C1 (`refs/hallmonitor/C1`, from E6)

Riskiest changed files: app/service.py (risk 2.37), app/ratelimit.py (risk 2.59)
