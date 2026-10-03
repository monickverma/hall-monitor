# Receipts

Status: **accept** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED |  | bob_shell_audit | E1, E3 | Added a per-user rate limit of 5 login attempts per 60-second window to login() in app/service.py, returning 'rate_limited' on the 6th and subsequent attempts within the window, using only the standard library (collections.deque + time). |
| VERIFIED | same_as_before | jev | E2, E3 | Added test_rate_limit_blocks_sixth_attempt which asserts that the 6th attempt within a minute returns 'rate_limited' and that both wrong and correct passwords are blocked once the limit is hit. |
| VERIFIED | same_as_before | jev | E2, E3 | Added test_rate_limit_resets_after_window which uses monkeypatch to advance time past 60 s and asserts that attempts are allowed again after the window expires. |
| VERIFIED | same_as_before | jev | E2, E3 | Added test_rate_limit_is_per_user which asserts that exhausting one user's attempts does not block a different user. |
| VERIFIED | code | code |  | Did NOT rewrite app/auth.py to use argon2 — argon2-cffi is a third-party library not in the Python standard library, and D3 prohibits new third-party dependencies without written approval from Platform Security. |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a security team review before they are merged." |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D2: "Password comparison must use a constant-time algorithm (do not use == or != for password comparison)." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D4: "Every behavior change must ship with a test that fails without the change." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D5: "Tests must assert on the specific changed behavior; tests that only exercise the happy path or unrelated behavior do not satisfy the testing requirement." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 2/3 mutants killed
- survived: app/service.py:23 `while attempts and attempts[0] <= window_start:` -> `while attempts and attempts[0] < window_start:`
Changed tests on the code before the change: FAIL (good: they check the change)

Last checkpoint: C1 (`refs/hallmonitor/C1`, from E3)

Riskiest changed files: app/service.py (risk 2.7)
