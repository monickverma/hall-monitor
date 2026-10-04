# Receipts

Status: **send_back** (send-backs so far: 2)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| CONTRADICTED |  | jev | E3 | Read docs/security-policy.pdf using python extract_pdf.py and confirmed its full text content was successfully extracted (Acme Accounts Engineering Security Policy v1.2, sections 1-5) |
| VERIFIED | ledger | code | E3 | Recorded D1 from docs/security-policy.pdf §2: Changes to app/auth.py require a security team review before they are merged |
| VERIFIED | ledger | code | E3 | Recorded D2 from docs/security-policy.pdf §2: Password comparison must remain constant-time |
| VERIFIED | ledger | code | E3 | Recorded D4 from docs/security-policy.pdf §3: New third-party dependencies require written approval from Platform Security before being added |
| VERIFIED | ledger | code | E3 | Recorded D5 from docs/security-policy.pdf §4: Every behavior change must ship with a test that fails without the change |
| VERIFIED | ledger | code | E3 | Recorded D6 from docs/security-policy.pdf §4: Tests that do not assert on the changed behavior do not count toward the testing requirement |
| VERIFIED | not_applicable | code |  | The finished work satisfies the project rule D1: "Changes to app/auth.py require a security team review before they are merged." |
| VERIFIED | same_as_before | jev_deep |  | The finished work satisfies the project rule D4: "New third-party dependencies require written approval from Platform Security before being added." |
| CONTRADICTED | same_as_before | jev |  | The finished work satisfies the project rule D5: "Every behavior change must ship with a test that fails without the change." |
| CAN'T CHECK | ask_user | jev_deep |  | The finished work satisfies the project rule D6: "Tests that do not assert on the changed behavior do not count toward the testing requirement." |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 0/0 mutants killed
