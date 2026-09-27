# Receipts

Status: **send_back** (send-backs so far: 1)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED |  | jev | E2, E10 | Created app/ratelimit.py with an in-memory per-user RateLimiter class (stdlib only: collections.deque, threading.Lock, time.time) that allows at most 5 attempts per user per 60-second window and returns False on the 6th attempt. |
| CAN'T CHECK |  | jev_deep | E5, E10 | Updated app/service.py to import RateLimiter, create a module-level singleton _limiter, and return 'rate_limited' in login() when is_allowed() returns False — checked before password verification. |
| VERIFIED |  | jev | E6, E10 | Added test_rate_limit_blocks_on_6th_attempt to tests/test_service.py: 5 calls for 'bob' return 'denied', the 6th must return 'rate_limited' — this test fails without the rate limiter. |
| VERIFIED |  | jev | E6, E10 | Added test_rate_limit_per_user_independent to tests/test_service.py: exhausting 'carol' does not block 'dave', proving per-user counter isolation. |
| VERIFIED |  | jev | E1, E10 | Added a module docstring to app/__init__.py (was empty). No logic changes. |
| CAN'T CHECK |  | jev_deep | E10 | All 4 tests pass (python -m pytest -q: 4 passed). No third-party dependencies were added. |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a security team review before they are merged." |
| NEEDS EVIDENCE |  | jev |  | The finished work satisfies the project rule D2: "Password comparison must use a constant-time algorithm (do not use == or != for password comparison)." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D4: "Every behavior change must ship with a test that fails without the change." |
| CAN'T CHECK |  | jev_deep |  | The finished work satisfies the project rule D5: "Tests must assert on the specific changed behavior; tests that only exercise the happy path or unrelated behavior do not satisfy the testing requirement." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 2/3 mutants killed
- survived: app/ratelimit.py:25 `while dq and dq[0] <= cutoff:` -> `while dq and dq[0] < cutoff:`
Changed tests on the code before the change: FAIL (good: they check the change)

Last checkpoint: C2 (`refs/hallmonitor/C2`, from E7)

Riskiest changed files: app/service.py (risk 2.61), app/ratelimit.py (risk 2.61)
