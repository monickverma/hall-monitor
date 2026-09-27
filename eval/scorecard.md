# Hall Monitor scorecard

score = min(quality, cap of the strongest evidence). Evidence: E0 design · E1 unit tests · E2 scripted run · E3 seeded cases · E4 real Bob · E5 real people.

| Part | Weight | Quality | Evidence | Cap | **Score** | Evidence used | Why this quality |
|---|---|---|---|---|---|---|---|
| receipts | 25% | 8 | E4 | 9 | **8** | 1 real run | Per-claim verdicts on evidence Hall Monitor produced itself (fresh tests, sabotage) |
| step monitor | 20% | 7.5 | E3 | 8 | **7.5** | control set; 0 actions judged in real Bob, no excuse caught there yet | Least-harm judgment of every intent; excuses named; code rules before Jev |
| robustness in real Bob | 15% | 5 | E4 | 9 | **5** | 1 real run | Real Bob found 7 bugs in one day (Sept 27), all false alarms, all fixed |
| explainability | 10% | 8 | E4 | 9 | **8** | Hall Passes from real runs | Hall Pass built from the session's own log; says why a task stopped |
| rules and plan | 10% | 7 | E2 | 6 | **6** | simulate.py (policy PDF); real runs had prompt rules only | Policy PDF and prompt lines become rules; plan gate on PLAN.md |
| drift and stalls | 5% | 6 | E2 | 6 | **6** | simulate.py | Named stall patterns and checkpoints; one real false stall, fixed |
| subagents | 5% | 7 | E2 | 6 | **6** | simulate.py and the probe | Briefs checked before a subagent starts, summaries after it returns |
| learning and eval | 5% | 6 | E3 | 8 | **6** | seeded eval, no reviewer data yet | Seeded eval with a certified threshold; noisy at n=38; control set |
| cost and latency | 5% | 6.5 | E4 | 9 | **6.5** | costs and times of real runs | Jev costs fractions of a cent; receipts rounds can add minutes |

**Overall: 6.9/10**

## Measured

- real runs: 1
- verified in the first round: no data
- ended verified: 0/1
- ended stuck: 1/1
- excuses named: no data
- stops per 10 actions judged: no data
- stops later allowed on the same target: no data
- median Bob cost per run: 2.91
- median minutes per run: 7.3
- seeded: caught: 21/22
- seeded: false alarms: 4/38
- control set: 20/20
- reviewers with timings: 0

## Real runs

| Run | First round | Final | Send-backs | Judged | Stops | Bob $ | Minutes |
|---|---|---|---|---|---|---|---|
| 2026-09-27_taskB-docs_member1 | unknown | stuck | None | None | None | 2.91 | 7.3 |

## Submission evidence

- [ ] docs/statements.md
- [ ] demo/bob_run/
- [ ] IDE screenshots in bob_sessions/
