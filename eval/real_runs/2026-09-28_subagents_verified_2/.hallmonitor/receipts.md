# Receipts

Status: **accept** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED |  | jev | E1 | Created app/ratelimit.py with is_rate_limited(user) that uses a sliding 60-second window (collections.deque + threading.Lock, time.monotonic), returns True on the 6th attempt within the window. Standard library only (satisfies D3, D6). |
| VERIFIED |  | jev_deep | E2 | Wired is_rate_limited into login() in app/service.py: if rate-limited, returns 'rate_limited' before password check. |
| VERIFIED |  | bob_shell_audit | E3, E4, E5, E6 | Added test_sixth_attempt_is_rate_limited to tests/test_service.py: asserts login() returns 'rate_limited' on the 6th attempt within a minute — fails without the rate-limit change (satisfies D4, D5). |
| VERIFIED |  | jev_deep | E3, E4, E5, E6 | Added test_fifth_attempt_not_rate_limited to tests/test_service.py: asserts the 5th attempt is NOT blocked (satisfies D5 boundary assertion). |
| VERIFIED |  | jev | E6 | All 4 tests pass (including both new rate-limit tests). |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a security team review before they are merged." |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D2: "Password comparison must use a constant-time algorithm (do not use == or != for password comparison)." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D4: "Every behavior change must ship with a test that fails without the change." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D5: "Tests must assert on the specific changed behavior; tests that only exercise the happy path or unrelated behavior do not satisfy the testing requirement." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 2/3 mutants killed
- survived: app/ratelimit.py:27 `while window and window[0] <= cutoff:` -> `while window and window[0] < cutoff:`
Changed tests on the code before the change: FAIL (good: they check the change)

Last checkpoint: C1 (`refs/hallmonitor/C1`, from E6)

Riskiest changed files: app/service.py (risk 2.72), app/ratelimit.py (risk 2.98)
