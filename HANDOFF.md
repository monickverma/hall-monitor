# Handoff to the cloud session (delete this file in your PR)

**Current objective:** finish Hall Monitor's remaining engineering for the IBM Bob 2.0 Hackathon on lablab.ai, without running IBM Bob, and report it in one PR. Deadline: Sun Sept 27, 20:30 IST (15:00 UTC). Nobody will answer questions; put everything in the PR description.

## What Hall Monitor is

It improves ONE developer workflow: **code review of AI-written changes**. Bob (IBM's AI coding IDE) does the work; Hall Monitor supervises every step through Bob's hooks and an MCP server, and makes Bob prove "done" with receipts. Jev (TypeSafe System One, `typesafe-sdk`, key in `TYPESAFE_API_KEY`, pinned `jev-1.13.0`, $0.042 per 1M input tokens) makes the cheap judgments.

Six loops over one shared state in `.hallmonitor/`:
- **L0 rules and plan:** `/decisions` reads a policy PDF into a rule ledger; PLAN.md passes a certificate gate.
- **L1 step:** Bob declares intents (`declare_intent`); `policy.py` picks the least-harm action; PreToolUse enforces it; `explain_block` tells Bob why.
- **L2 drift:** `evidence.py` numbers every edit and command (E1, E2, ...); passing tests become git checkpoints (`refs/hallmonitor/C<n>`); a stall counter with named patterns stops and asks past the limit.
- **L3 subagents:** briefs checked before start, summaries on return.
- **L4 Receipts (`receipts.py`):** claims cite E-IDs; `certify()` checks in code first (unknown_file, uncited, unknown, failed, out_of_scope, stale, replay_mismatch), then sabotage and extreme mutation in a scratch copy, then Jev. STUCK after 2 send-backs.
- **L5 learn (`eval/`):** seeded eval with a certified threshold, a 20-case control set, bulk classification, a human review pilot; cross-session lessons feed the next briefing.

## Already completed (all on `v4.1-evidence-receipts`, which is PR #1 into `main`)

- T1–T6 of the v4.1 plan; PR #2 (fixes from the first real Bob runs) and PR #3 (v4.2: 123 tests, CI, fabricated-file check, extreme mutation, cross-session lessons, "going in circles" stall, deep review off by default) are merged.
- `a5ac3c1` ignores `.claude/`.
- `0e3d6fc` fixes false mismatch blocks found in real Bob: Jev saw only the first 1,200 characters of an edit. Now up to 6,000 with a marker, and MATCHES_INTENT accepts one step of the declared change.
- `37e69bb` README and ARCHITECTURE written by IBM Bob (task B, Bob Shell, supervised); `9caa1fa` review fixes to them.
- Gates on the v4.1 head: 125 tests; control set 20/20; `simulate.py` VERIFIED, 9 stops, 0 `"stage": "error"` events. The committed `eval/*.json` are from a83a691: 21/22 caught, 3/38 false alarms, agreement 56/60.
- Probe in real Bob (IDE 2.2.0, Bob Shell 2.0.5): hooks fire under `bob run` and in subagents; subagents can call MCP; claims arrive as objects; PostToolUse has output but no exit code; Plan mode writes PLAN.md at the root; edit tools send absolute Windows paths (`store.rel_path`). Unverified: checkpoint refs alongside Bob's rollback, `alwaysAllow` in the IDE, the unit of `session_costs`.

## This branch (`receipts-diff-budget`)

One commit on top of `9caa1fa`, found when Bob's docs task ended STUCK: Receipts showed Jev at most 60 added lines per file and 2,500 characters of diff, so true claims about long doc edits came back "says nothing".
- `gitutil.diff_text`: up to 200 added lines per file, and markers for anything left out.
- `receipts.py`: focused budget 2,500 → 6,000. The deep look stays at 7,000: a seeded run at 12,000 gave 3 "can't check" deep-look verdicts.
- `evidence.is_test_command`: `pytest --collect-only` / `--co` is not a test run (it caused a false "breaking a passing state" stall).
- 127 tests pass. With deep at 12,000 the seeded eval gave 21/22 caught and 4/38 false alarms; the 7,000 version is **not yet gated**.

## Your tasks, in order

1. Run all four gates on this branch: `python -m pytest -q`; `python eval/control_set.py` (20/20); `python simulate.py` (VERIFIED, 9 stops, 0 error events in `demo/run/.hallmonitor/events.jsonl`); `python eval/seeded.py && python eval/score.py`. Accept if caught is at least 21/22 and false alarms are at most 3/38. Jev noise gives 2–4/38 between runs, so on 4/38 run it once more and report both. If it still fails, revert the budget change (keep the markers and the collect-only fix) and report that.
2. Commit the regenerated `eval/results.json` and `eval/summary.json`, but not `eval/review/form_*.csv`. Update the numbers in README's Eval section and ARCHITECTURE section 4 only if they changed.
3. Open a PR from this branch into `v4.1-evidence-receipts`. Delete this file in it. The description is your report: the gates before and after, what changed, anything reverted.

## Decisions already made (don't reopen)

- One workflow only: code review of AI-written changes.
- Deny-only: Jev can block, escalate or ask, never override a code rule to allow.
- Don't change harm weights, thresholds or question wording.
- Jev never sees Bob's summary, only cited evidence.
- Keep 7 MCP tools and 5 hooks; the demo and runbook count them.
- The rule extractor records every line of the user's prompt as a rule. Don't change it: the demo relies on "Keep the counters in memory, no Redis" becoming a rule.
- T7 trust levels are dropped for time. Don't build them.
- Reserved for the team in IBM Bob: `docs/statements.md`, `demo/bob_run/`, `bob_sessions/`. Don't touch them.

## Safe rules

- Work only on `receipts-diff-budget`. Never push to `v4.1-evidence-receipts` or `main`, never force-push, merge, or change repo settings or visibility.
- Every commit keeps `python -m pytest -q` green.
- Never run `bob`: Bobcoins are reserved for the team's recorded demo.
- Check the key with `python -c "import os; print(bool(os.environ.get('TYPESAFE_API_KEY')))"` and never print it. Without it, say so at the top of the PR and stop after the unit tests.
- No personal information anywhere. End commit messages with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
