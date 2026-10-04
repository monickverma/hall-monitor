# Receipts

Status: **send_back** (send-backs so far: 1)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| CONTRADICTED |  | jev | E1 | Read docs/security-policy.pdf and extracted all engineering rules from sections 2, 3, and 4 |
| VERIFIED | ledger | code | E1 | Recorded D1: Changes to app/auth.py require a review by the security team before they are merged (§2) |
| VERIFIED | ledger | code | E1 | Recorded D2: Password comparison must remain constant-time (§2) |
| VERIFIED | ledger | code | E1 | Recorded D4: New third-party dependencies require written approval from Platform Security before being added (§3) |
| VERIFIED | ledger | code | E1 | Recorded D5: Every behavior change must ship with a test that fails without the change (§4) |
| VERIFIED | ledger | code | E1 | Recorded D6: Tests that do not assert on the changed behavior do not count toward the testing requirement (§4) |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 0/0 mutants killed
