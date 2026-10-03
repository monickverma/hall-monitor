# Receipts

Status: **accept** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED | ledger | code | E2 | Recorded decision D1 in Hall Monitor: Changes to app/auth.py require a review by the security team before they are merged |
| VERIFIED | ledger | code | E2 | Recorded decision D2 in Hall Monitor: Password comparison must remain constant-time |
| VERIFIED | ledger | code | E2 | Recorded decision D3 in Hall Monitor: Services must use only the Python standard library; new third-party dependencies require written approval from Platform Security |
| VERIFIED | ledger | code | E2 | Recorded decision D4 in Hall Monitor: Every behavior change must ship with a test that fails without the change; tests that do not assert on the changed behavior do not count |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 0/0 mutants killed
