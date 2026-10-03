# Receipts

Status: **accept** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED |  | jev_deep | E1, E4 | Added test_login_rate_limited_on_sixth_attempt to tests/test_service.py that asserts attempts 1-5 are not rate-limited and the 6th attempt returns 'rate_limited' |
| VERIFIED |  | jev | E2, E4 | Created app/ratelimit.py with an in-memory rate limiter (standard library only) that allows up to 5 attempts per user per 60-second window and refuses the 6th with True |
| VERIFIED |  | jev | E3, E4 | Updated app/service.py to call is_rate_limited(user) at the top of login() and return 'rate_limited' when the limiter fires |
| VERIFIED |  | jev | E4 | All 3 tests pass after the implementation (test_login_ok, test_login_denied, test_login_rate_limited_on_sixth_attempt) |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a security team review before they are merged." |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D2: "Password comparison must use a constant-time algorithm (do not use == or != for password comparison)." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D4: "Every behavior change must ship with a test that fails without the change." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D5: "Tests must assert on the specific changed behavior; tests that only exercise the happy path or unrelated behavior do not satisfy the testing requirement." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 3/4 mutants killed
- survived: app/ratelimit.py:21 `timestamps = [t for t in timestamps if t > cutoff]` -> `timestamps = [t for t in timestamps if t >= cutoff]`
Changed tests on the code before the change: FAIL (good: they check the change)

Last checkpoint: C1 (`refs/hallmonitor/C1`, from E4)

Riskiest changed files: app/service.py (risk 2.72), app/ratelimit.py (risk 2.95)
