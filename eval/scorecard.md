# Hall Monitor scorecard

score = min(quality, cap of the strongest evidence). Evidence: E0 design · E1 unit tests · E2 scripted run · E3 seeded cases · E4 real Bob · E5 real people.

| Part | Weight | Quality | Evidence | Cap | **Score** | Evidence used | Why this quality |
|---|---|---|---|---|---|---|---|
| receipts | 25% | 8.5 | E4 | 9 | **8.5** | 8 real runs | Per-claim verdicts on evidence Hall Monitor produced itself: fresh tests, sabotage, and changed tests re-run on the code before the change |
| step monitor | 20% | 7.5 | E4 | 9 | **7.5** | 2 excuses named in real Bob | Least-harm judgment of every intent; excuses named; code rules before Jev |
| robustness in real Bob | 15% | 5.5 | E4 | 9 | **5.5** | 8 real runs | Single-agent tasks now verify in the first round in real Bob (docs, /decisions x2); the fixes for 12 earlier false alarms held there. The task with parallel subagents hasn't verified yet: its last run found 4 more false alarms, fixed but not re-run |
| explainability | 10% | 8 | E4 | 9 | **8** | Hall Passes from real runs | Hall Pass built from the session's own log; says why a task stopped |
| rules and plan | 10% | 7 | E4 | 9 | **7** | rules from a document in a real run | Policy PDF and prompt lines become rules; plan gate on PLAN.md |
| drift and stalls | 5% | 6 | E4 | 9 | **6** | stalls flagged in real runs | Named stall patterns and checkpoints; one real false stall, fixed |
| subagents | 5% | 7 | E4 | 9 | **7** | subagents checked in real runs | Briefs checked before a subagent starts, summaries after it returns |
| learning and eval | 5% | 6.5 | E3 | 8 | **6.5** | seeded eval, no reviewer data yet | Seeded eval with a certified threshold (noisy at n=38); control set; Jev labels the real Bob sessions for the review queue; no human labels yet |
| cost and latency | 5% | 6.5 | E4 | 9 | **6.5** | costs and times of real runs | Jev costs fractions of a cent; receipts rounds can add minutes |

**Overall: 7.2/10**

## Measured

- real runs: 8
- verified in the first round: 3/7
- ended verified: 3/8
- ended stuck: 4/8
- excuses named: 2
- stops per 10 actions judged: 1.7
- stops later allowed on the same target: 5/11
- median Bob cost per run: 0.83
- median minutes per run: 1.5
- seeded: caught: 21/22
- seeded: false alarms: 2/38
- control set: 20/20
- reviewers with timings: 0

## Real runs

| Run | First round | Final | Send-backs | Judged | Stops | Bob $ | Minutes |
|---|---|---|---|---|---|---|---|
| 2026-09-27_taskB-docs_member1 | unknown | stuck | None | None | None | 2.91 | 7.3 |
| 2026-09-27_decisions-then-subagents_stuck | send_back | stuck | 3 | 19 | 5 |  | 0.0 |
| 2026-09-27_docs_no-jev-key | none | none | 0 | 1 | 1 | 0.19 | 0.5 |
| 2026-09-27_docs_stuck-before-fix | send_back | stuck | 3 | 5 | 1 | 0.39 | 0.7 |
| 2026-09-27_docs_verified | accept | accept | 0 | 2 | 0 | 0.18 | 0.3 |
| 2026-09-27_final_decisions-then-subagents_stuck | accept | stuck | 4 | 16 | 1 | 1.03 | 1.9 |
| 2026-09-27_merged_decisions-then-subagents_sent-back | accept | accept | 0 | 12 | 3 | 0.84 | 1.5 |
| 2026-09-27_ratelimit-demo_verified | audit | accept | 0 | 9 | 0 | 0.83 | 10.4 |

## Submission evidence

- [ ] docs/statements.md
- [ ] demo/bob_run/
- [ ] IDE screenshots in bob_sessions/
