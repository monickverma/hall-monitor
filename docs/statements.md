# Submission Statements

## Problem & Solution

Hall Monitor improves one developer workflow: code review of AI-written changes.

Of 23,247 agent-written pull requests, 1.7% had descriptions that didn't match the code. The most common mismatch (45.4%) claimed changes that were never made, and those PRs were accepted 28.3% of the time, against 80.0% for the rest (MSR 2026).

The root cause is that a reviewer reading an agent's summary has no independent evidence that the summary is true. The agent wrote both the code and the description, so a drift between them goes unnoticed until it reaches production.

Hall Monitor fixes this by supervising the agent as it works, not after. It uses three mechanisms. First, rules extracted from policy documents are enforced on every action: before an edit runs, the agent must declare what it will do and why, and Hall Monitor checks the declared intent against active rules and flags rationalizations by name (exception, priority inversion, goal substitution, and others). Second, every edit and command becomes a numbered receipt; when the agent says it is done, each claim must cite the receipt IDs that prove it, and Hall Monitor checks those receipts against the diff, a fresh test run, and sabotage mutants that break the changed code to confirm the tests would catch the break. Third, if a claim cannot be verified after two send-backs, Hall Monitor stops and hands the decision to the reviewer.

The result is a Hall Pass: a one-page report of what was checked, what was blocked, and what the reviewer should still look at. The reviewer sees the evidence, not just the summary.

Hall Monitor is for developers who use IBM Bob in Supervised mode. It runs entirely on Bob's own features: no separate server, no new tools, and no changes to the codebase under review. A team member loads a policy document with `/decisions`, runs a task, and calls `/hall-pass` when Bob reports it done. The Hall Pass is published as a Bob artifact.

On 60 seeded claims (22 false, 38 true, on claims we seeded ourselves), Hall Monitor caught 21 of 22 false claims with 2 false alarms, a Brier score of 0.0312, and agreement of 57 out of 60. At a verification threshold of 0.5, 25 of 34 claims were accepted with 1 wrong and an upper bound of 0.15 at 90% confidence. The two verified runs of the full demo task on September 28 cost $1.95 and $2.44, including a Bob Shell audit.

---

## IBM Bob Usage

Hall Monitor runs on IBM Bob IDE 2.2.0 and Bob Shell 2.0.5. Every part of it uses a documented Bob feature; none requires changes to Bob itself.

**Bob features Hall Monitor uses** (from ARCHITECTURE.md):

- **Lifecycle hooks** (SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop): enforcement runs in PreToolUse hooks (exit 2 blocks the tool); evidence collection runs in PostToolUse hooks; the Hall Pass is written at Stop. Hooks fire inside subagents and under `bob run`.
- **MCP server** (`.bob/mcp.json`): all verdicts and block reasons reach Bob through MCP, because hook stderr goes to Bob's logs, not the model. The seven tools are `declare_intent`, `explain_block`, `record_decision`, `list_decisions`, `list_evidence`, `submit_claims`, and `hall_pass`.
- **Document understanding** (native PDF; `office_read`/`office_edit`): `/decisions docs/security-policy.pdf` has Bob read the policy and record each rule with its section and a verbatim quote. `/export-ledger` writes the receipts ledger to an Excel file and validates it with `office_read`.
- **Custom modes**: the 🛂 Supervised mode grants read, edit, execute, MCP, skill, subagent, workflow, and todo groups. The 🔎 Receipts Auditor mode omits the edit group, so the auditor cannot alter the evidence it checks.
- **Subagents** (`spawn_subagent`): every subagent brief is checked before it starts; the returned summary is checked for drift and surfaces as a flag in the next `declare_intent` result. Uncertain claims are audited by a read-only `explore` subagent.
- **Bob Shell** (`bob run --format json`): supervised headless runs as a CI gate, with Hall Monitor's hooks and MCP server active.
- **`create_html_artifact`**: `/hall-pass` publishes the Hall Pass as a shareable Bob artifact.
- **Skills and slash commands**: `/decisions`, `/receipts`, `/audit`, `/hall-pass`, and `/export-ledger`.

**What Bob built in this repo** (from the table in BOB_RUNBOOK.md step 5):

- **Task B (docs):** Bob updated README.md and ARCHITECTURE.md in a supervised Bob Shell session (`2026-09-27_docs_verified`).
- **Task C (statements):** Bob wrote docs/statements.md in the Bob IDE, supervised by Hall Monitor.

The demo task — adding a per-user rate limit to `login()` using two parallel subagents — verified in two Bob Shell runs on September 28 (`2026-09-28_subagents_verified`, `2026-09-28_subagents_verified_2`). Those runs produced `demo/bob_run/` and are logged in `eval/real_runs/`.
