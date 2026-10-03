# Receipts

Status: **accept** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED | same_as_before | jev_deep | E1, E9 | Added per-user rate limit of 5 login attempts per minute to login() in app/service.py using only stdlib (time, collections.deque); returns 'too_many_requests' on the 6th attempt within 60 seconds |
| VERIFIED | same_as_before | jev | E2, E8, E9 | Added test_login_rate_limited in tests/test_service.py that asserts the 6th login attempt within a minute returns 'too_many_requests'; this test fails if the rate-limit code is removed |
| VERIFIED |  | jev+audit | E8, E9 | Added test_login_rate_limit_resets_after_window in tests/test_service.py that freezes time via unittest.mock.patch and verifies attempts exactly at the 60-second boundary are dropped (>= semantics); this test fails with the >= vs > mutant |
| VERIFIED | same_as_before | jev | E9 | All 4 tests pass after all changes |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a security team review before they are merged." |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D2: "Password comparison must use a constant-time algorithm (do not use == or != for password comparison)." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D4: "Every behavior change must ship with a test that fails without the change." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D5: "Tests must assert on the specific changed behavior; tests that only exercise the happy path or unrelated behavior do not satisfy the testing requirement." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 3/3 mutants killed
Changed tests on the code before the change: FAIL (good: they check the change)

Last checkpoint: C3 (`refs/hallmonitor/C3`, from E9)

Riskiest changed files: app/service.py (risk 2.47)
