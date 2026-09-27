# Receipts

Status: **accept** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED | same_as_before | jev | E2 | Created app/ratelimit.py with a RateLimiter class (stdlib only: collections.deque, collections.defaultdict, time.time) and a module-level singleton `limiter`. is_allowed(user) uses a 60-second sliding window and returns False on the 6th+ attempt within the window. |
| VERIFIED | same_as_before | jev_deep | E1 | Updated app/service.py to import `limiter` from app.ratelimit and call limiter.is_allowed(user) at the top of login(); returns 'rate_limited' immediately if the user is over the limit. |
| VERIFIED |  | jev+audit | E3, E8 | Added test_rate_limit_blocks_sixth_attempt to tests/test_service.py: asserts the first 5 attempts are not rate-limited and the 6th returns 'rate_limited'. This test fails without the is_allowed guard. |
| VERIFIED | same_as_before | jev | E4, E8 | Added test_rate_limit_resets_after_window to tests/test_service.py: monkeypatches time.time to advance 61 seconds and asserts the attempt is allowed again after the window expires. |
| VERIFIED | same_as_before | jev | E8 | All 4 tests pass (2 pre-existing + 2 new) after all changes. |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a security team review before they are merged." |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D2: "Password comparison must use a constant-time algorithm (do not use == or != for password comparison)." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D4: "Every behavior change must ship with a test that fails without the change." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D5: "Tests must assert on the specific changed behavior; tests that only exercise the happy path or unrelated behavior do not satisfy the testing requirement." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 3/4 mutants killed
- survived: app/ratelimit.py:27 `while window and window[0] <= cutoff:` -> `while window and window[0] < cutoff:`
Changed tests on the code before the change: FAIL (good: they check the change)

Last checkpoint: C1 (`refs/hallmonitor/C1`, from E5)

Riskiest changed files: app/service.py (risk 2.58), app/ratelimit.py (risk 2.98)
