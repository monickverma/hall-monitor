# Receipts

Status: **accept** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED | same_as_before | bob_shell_audit | E1 | Added a guard in login() in app/service.py that raises ValueError when username is empty |
| VERIFIED |  | bob_shell_audit | E2, E3 | Added test_login_empty_username_raises in tests/test_service.py that fails without the change (D4/D5), using only the standard library (D3) |
| VERIFIED | same_as_before | jev | E3 | All 3 tests pass after the changes |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a security team review before they are merged." |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D2: "Password comparison must use a constant-time algorithm (do not use == or != for password comparison)." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D4: "Every behavior change must ship with a test that fails without the change." |
| VERIFIED | same_as_before | jev_deep |  | The finished work satisfies the project rule D5: "Tests must assert on the specific changed behavior; tests that only exercise the happy path or unrelated behavior do not satisfy the testing requirement." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 0/0 mutants killed
Changed tests on the code before the change: FAIL (good: they check the change)

Last checkpoint: C1 (`refs/hallmonitor/C1`, from E3)
