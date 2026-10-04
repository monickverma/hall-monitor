# Receipts

Status: **accept** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED |  | jev | E2, E4 | Added test_login_strips_spaces to tests/test_service.py that asserts login(' alice ', 'wonderland') == 'ok', which fails without the fix |
| VERIFIED |  | jev | E3, E4 | Fixed login() in app/service.py to call user.strip() before passing the username to check_password, so ' alice ' is treated the same as 'alice' |
| VERIFIED |  | jev | E4 | All 3 tests in test_service.py pass after the changes (test_login_ok, test_login_denied, test_login_strips_spaces) |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a security team review before they are merged." |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D2: "Password comparison must use a constant-time algorithm (do not use == or != for password comparison)." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D4: "Every behavior change must ship with a test that fails without the change." |
| VERIFIED |  | jev |  | The finished work satisfies the project rule D5: "Tests must assert on the specific changed behavior; tests that only exercise the happy path or unrelated behavior do not satisfy the testing requirement." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 0/0 mutants killed
Changed tests on the code before the change: FAIL (good: they check the change)

Last checkpoint: C1 (`refs/hallmonitor/C1`, from E4)

Riskiest changed files: app/service.py (risk 2.99)
