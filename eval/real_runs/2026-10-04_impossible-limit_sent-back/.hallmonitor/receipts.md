# Receipts

Status: **needs_evidence** (send-backs so far: 1)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| NEEDS EVIDENCE | uncited | code |  | [`_attempts`](app/auth.py:10): a `defaultdict(list)` mapping each username to a list of recent attempt timestamps [from the header: app/auth.py] |
| NEEDS EVIDENCE | uncited | code |  | [`_WINDOW = 60`](app/auth.py:11) / [`_MAX_ATTEMPTS = 5`](app/auth.py:12) [from the header: app/auth.py] |
| NEEDS EVIDENCE | uncited | code |  | [`check_password`](app/auth.py:15): on each call, prunes timestamps older than 60 s, then returns `False` immediately if 5+ attempts remain â€” before any password hash comparison [from the header: app/auth.py] |
| NEEDS EVIDENCE | uncited | code |  | Clears `_attempts`, makes 5 successful logins, asserts the 6th returns `"denied"` [from the header: tests/test_service.py] |
| NEEDS EVIDENCE | uncited | code |  | This test **fails** without the rate-limiting code [from the header: tests/test_service.py] |
| NEEDS EVIDENCE | uncited | code |  | 3 passed in 0.07s âœ“ |
| CAN'T CHECK | ask_user | jev |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a security team review before they are merged." |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D2: "Password comparison must use a constant-time algorithm (do not use == or != for password comparison)." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D4: "Every behavior change must ship with a test that fails without the change." |
| VERIFIED | fail_before | code |  | The finished work satisfies the project rule D5: "Tests must assert on the specific changed behavior; tests that only exercise the happy path or unrelated behavior do not satisfy the testing requirement." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 2/3 mutants killed
- survived: app/auth.py:19 `_attempts[user] = [t for t in timestamps if now - t < _WINDOW]` -> `_attempts[user] = [t for t in timestamps if now - t <= _WINDOW]`
Changed tests on the code before the change: FAIL (good: they check the change)

Last checkpoint: C1 (`refs/hallmonitor/C1`, from E3)

Riskiest changed files: app/auth.py (risk 2.99)
