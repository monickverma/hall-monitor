# Receipts

Status: **accept** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED | ledger | code | E1 | Recorded D1: Changes to app/auth.py require a review by the security team before they are merged (docs/security-policy.pdf §2). |
| VERIFIED | ledger | code | E1 | Recorded D2: Password comparison must remain constant-time (docs/security-policy.pdf §2). |
| VERIFIED | ledger | code | E1 | Recorded D3: Services must use only the Python standard library; new third-party dependencies require written approval from Platform Security (docs/security-policy.pdf §3). |
| VERIFIED | ledger | code | E1 | Recorded D4: Every behavior change must ship with a test that fails without the change; tests that do not assert on the changed behavior do not count (docs/security-policy.pdf §4). |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 0/0 mutants killed
