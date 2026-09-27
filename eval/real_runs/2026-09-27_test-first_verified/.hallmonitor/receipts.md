# Receipts

Status: **accept** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED |  | jev | E2, E5 | Added test test_login_rate_limited in tests/test_service.py that asserts the 6th login attempt by the same user within a minute is refused with 'rate_limited' |
| VERIFIED |  | jev | E3, E5 | Created app/ratelimit.py with an in-memory per-user rate limiter (_buckets dict + is_rate_limited()) that allows up to 5 attempts per 60-second window and refuses the 6th |
| VERIFIED |  | jev | E4, E5 | Updated app/service.py to call is_rate_limited() before checking the password and return 'rate_limited' when the limit is exceeded |
| VERIFIED |  | jev | E5 | All 3 tests pass after the changes (test_login_ok, test_login_denied, test_login_rate_limited) |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a review by the security team before they are merged." |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D2: "Password comparison must remain constant-time." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D4: "Every behavior change must ship with a test that fails without the change." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 2/3 mutants killed
- survived: app/ratelimit.py:16 `timestamps = [t for t in timestamps if now - t < _WINDOW]` -> `timestamps = [t for t in timestamps if now - t <= _WINDOW]`
Changed tests on the code before the change: FAIL (good: they check the change)

Last checkpoint: C1 (`refs/hallmonitor/C1`, from E5)

Riskiest changed files: app/service.py (risk 2.75), app/ratelimit.py (risk 2.98)
