# Receipts

Status: **accept** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED |  | jev | E1, E4 | Added rate limiter |

Fresh test run: pass (`python -m pytest -q`)
Sabotage: 2/3 mutants killed
- survived: app/service.py:18 `_attempts[user] = [t for t in attempts if t > window_start]` -> `_attempts[user] = [t for t in attempts if t >= window_start]`

Last checkpoint: C1 (`refs/hallmonitor/C1`, from E4)

Riskiest changed files: app/service.py (risk 2.7)
