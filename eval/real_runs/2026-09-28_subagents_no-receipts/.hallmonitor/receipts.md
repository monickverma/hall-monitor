# Receipts

Status: **send_back** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| CAN'T CHECK | jev_refused | refused | E1 | Updated app/service.py to import is_rate_limited from app.ratelimit and call it at the top of login(), returning 'rate_limited' before check_password when the user is rate limited |
| NEEDS EVIDENCE | stale | code | E7, E8, E15 | Added test_rate_limit_blocks_sixth_attempt to tests/test_service.py asserting that the 6th login call for 'ratelimituser_sixth' returns 'rate_limited'; this test fails if the rate-limit check is removed |
| NEEDS EVIDENCE | stale | code | E7, E8, E15 | Added test_rate_limit_allows_attempt_below_limit to tests/test_service.py asserting that the 4th login call for 'ratelimituser_below' does NOT return 'rate_limited', confirming calls below the threshold are allowed |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 0/0 mutants killed

Last checkpoint: C4 (`refs/hallmonitor/C4`, from E17)
