# Receipts

Status: **stuck** (send-backs so far: 3)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED |  | jev | E2, E4 | Updated app/service.py to import is_rate_limited from app.ratelimit and call it at the top of login(), returning 'rate_limited' before the password check when it returns True |
| NEEDS EVIDENCE | out_of_scope | code | E3, E4 | Added test_rate_limited_on_6th_attempt in tests/test_service.py: patches app.service.is_rate_limited with side_effect returning False x5 then True, asserts the 6th call returns 'rate_limited'; this test fails if login() does not check the rate limiter |
| NEEDS EVIDENCE | out_of_scope | code | E3, E4 | Added test_rate_limited_blocks_before_password_check in tests/test_service.py: patches is_rate_limited to return True and asserts check_password is never called and result is 'rate_limited' |
| NEEDS EVIDENCE |  | jev |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a security team review before they are merged." |
| VERIFIED |  | jev_deep |  | The finished work satisfies the project rule D4: "New third-party dependencies require written approval from Platform Security before being added." |
| CONTRADICTED |  | jev_deep |  | The finished work satisfies the project rule D5: "Every behavior change must ship with a test that fails without the change." |
| NEEDS EVIDENCE |  | jev_deep |  | The finished work satisfies the project rule D6: "Tests must assert on the specific changed behavior; tests that only exercise unrelated happy paths do not satisfy the testing requirement." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 2/3 mutants killed
- survived: app/ratelimit.py:25 `if now - window_start >= _WINDOW_SECONDS:` -> `if now - window_start > _WINDOW_SECONDS:`

Riskiest changed files: app/service.py (risk 2.7), app/ratelimit.py (risk 2.97)
