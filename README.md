# Hall Monitor: code review of AI-written changes, for IBM Bob

**The workflow it improves: code review of AI-written changes.** Today a reviewer has to re-check everything a coding agent claims ("wired it in", "added tests", "didn't touch auth"). Hall Monitor makes IBM Bob show receipts for its work while it works, so review starts from evidence instead of from scratch.

**What Hall Monitor does:**
- **Rules from policy documents:** Bob reads the rules from your `.pdf`, `.docx`, or `.xlsx` policy documents, and Hall Monitor enforces them on every action Bob and its subagents take.
- **Declared intents, with excuses named:** before every edit or command Bob declares what it will do; Hall Monitor names rationalization patterns ("just this once", "it's faster", "the spirit of the rule allows it") and rejects them before anything runs.
- **Receipts:** every claim Bob makes cites E-IDs from `list_evidence`. Code checks the receipts first — including whether every file a claim names actually exists in the repo (`unknown_file`, tier 0) — and then Jev checks them. Sabotage mutants run in a scratch copy of the repo (if the clean copy can't pass its tests, they run in place and each file is restored right after); extreme mutation (replacing a whole function body) finds pseudo-tested functions. Uncertain claims escalate to a read-only Bob auditor subagent, then to you. Hall Monitor stops and asks the user after 2 send-backs, naming the checkpoint to restore. A project rule that comes back "needs evidence" again on the same diff goes to you as a question instead of using up a send-back.
- **Checkpoints:** a passing test run becomes a git checkpoint (`refs/hallmonitor/C<n>`), a state Bob can return to.
- **The Hall Pass:** a one-page HTML report of the session. Hall Monitor writes it to `.hallmonitor/hall-pass.html`, and `/hall-pass` has Bob publish it with `create_html_artifact`.

Code rules decide what they can (protected folders, safe commands, dependencies, stale test runs, files that don't exist); TypeSafe's Jev judges the rest in one cheap parallel call. A whole supervised session costs about $0.003 of Jev.

See [ARCHITECTURE.md](ARCHITECTURE.md) for how each Bob feature is used and the decision flow.

## Install and first run

Needs Python 3.11+ and a TypeSafe API key for Jev, set as `TYPESAFE_API_KEY` in the environment (never in a file). Bob Shell runs also need `BOB_API_KEY`.

```bash
pip install -r requirements.txt
python scripts/doctor.py   # checks Python, packages, keys and Bob Shell
python simulate.py         # the scripted demo, no Bob needed
```

Then open `demo/run/.hallmonitor/hall-pass.html`.

For a real Bob session, `python scripts/setup_demo.py C:/hm-demo` creates a fresh demo repo with Hall Monitor installed. Then follow [BOB_RUNBOOK.md](BOB_RUNBOOK.md): the 30-minute probe ([PROBE.md](PROBE.md)), then the demo task under Hall Monitor, with the exact prompts and the screenshots to save.

To install Hall Monitor into your own repo:

```bash
python scripts/install.py path/to/your/repo
python scripts/doctor.py path/to/your/repo --live   # checks the install, and that Jev and Bob Shell answer (about $0.03)
```

To remove it again: `python scripts/install.py --uninstall path/to/your/repo` (the repo's own hooks, servers and modes stay; so do Hall Monitor's records in `.hallmonitor/`).

Then:
1. Open the repo as a **trusted** workspace (hooks respect workspace trust), check **Settings → Hooks** lists the five hooks, and approve the `hall-monitor` MCP server.
2. Switch to the **🛂 Supervised** mode.
3. Run `/decisions docs/your-policy.pdf`, or `/decisions AGENTS.md` if your rules live in the repo's agent guidance.
4. Give Bob the task. Bob declares intents, Hall Monitor judges them, and hooks enforce them.
5. When Bob is done, it calls `submit_claims`, fixes whatever comes back unverified, and finishes with `/hall-pass` (Bob publishes the report with `create_html_artifact`). `/export-ledger docs/ledger.xlsx` writes the decisions and receipts to Excel with Bob's `office_edit`.

This installs, under `.bob/`: hooks (`settings.json`), the MCP server (`mcp.json`), two custom modes, four skills, five slash commands, and Plan-mode rules.

**CI / headless:** `python scripts/headless.py <repo> "<task>"` runs Bob Shell (`bob run --mode supervised --format stream-json`, keeping the run's transcript and Bob's final answer) and exits non-zero unless Receipts verified the work. Under `bob run` every tool is pre-approved, so Hall Monitor is the only gate. `TYPESAFE_API_KEY` and Bob Shell's `BOB_API_KEY` must be in the environment. Never commit them. On a fresh runner, `bob run` stops at IBM's license: accept it once with `bob`, or set `HM_BOB_ACCEPT_LICENSE=1` (a key of type 'general' also needs `HM_BOB_TEAM_ID`).

## Running the tests

```bash
python -m pytest -q
```

Runs **245 tests** with no API key needed. CI runs them on Ubuntu and Windows with Python 3.11 and 3.13 (see [`.github/workflows/tests.yml`](.github/workflows/tests.yml)).

**Live gates** (need `TYPESAFE_API_KEY`):
- `python eval/control_set.py` — 24 actions run through the step judge: 12 must be blocked and 12 must be allowed
- `python simulate.py` — the full scripted demo
- `eval/seeded.py` then `eval/score.py` — seeded eval
- `python simulate.py --deep-review` — shows deep review (off by default in the demo)

**Config keys** (set in `.hallmonitor/config.json` in your repo):

| Key | Default | Effect |
|---|---|---|
| `max_extreme_mutants` | `3` | Functions tried for extreme mutation per claim; `0` turns it off |
| `extreme_timeout` | `60` | Seconds per test run during extreme mutation |
| `deep_review` | `false` | When `true`, Receipts requests explore-subagent reviews of the riskiest changed files after claims verify |

## Eval

Numbers are from `eval/summary.json` (on claims we seeded ourselves) and `eval/review_queue_summary.json` (on events from our scripted, seeded and real Bob sessions).

**Claim verification** (`eval/summary.json`, n=60 claims, 10 scenario variants):
- 21/22 false claims caught; 2 false alarms out of 38 true claims; agreement 57/60; Brier score 0.0312. Jev's verdicts vary between runs: with fail-before evidence, three runs gave 1, 2 and 2 false alarms; seven runs before it gave 1 to 5 (mean 3.3).
- Certified auto-accept threshold for the Jev tier: 0.5. Above it, 25 verdicts were accepted and 1 was wrong; the error rate is at most 14.7% at 90% confidence (n=34 claims).

**Bulk classification** (`eval/review_queue_summary.json`, n=183 events, 18 sessions: the first 7 real Bob Shell runs in `eval/real_runs/` (later runs were added after it was computed), the scripted demo, and 10 seeded sessions):
- Jev labelled all 183 events in 6.0 s for $0.0057 (135,024 input tokens) and flagged 51.3% as needing a person. That rate is Jev's alone: the human labels that would correct it (prediction-powered inference) aren't collected yet; `eval/review_queue_sample.csv` holds the 30-event blind sample for a person to label.
- Failure forms: none 124, inaccurate self-report 28, operational execution error 16, constraint violation 13, faulty implementation 1, self-initiated overreach 1.

**Human review pilot:** no data yet. Reviewers answer on a web page (each picks a slot, judges 16 claims with and without Hall Monitor, timed); `python eval/import_review.py <dir>` brings their answers into the review sheets.

**Scorecard** (`python eval/scorecard.py`, writes `eval/scorecard.md`): each part of Hall Monitor is rated for quality, capped by the strongest evidence behind it (design, unit tests, the scripted run, seeded cases, real Bob runs, real people). It reads the eval files above and the real Bob Shell runs kept in `eval/real_runs/`.

## Results in real Bob, and limits

**With and without Hall Monitor** (`eval/compare.py`, `eval/compare/summary.md`): 12 rule-breaking tasks, each run by real Bob Shell in a fresh demo repo with Hall Monitor and again without it; a check in code reads the final repo. Without Hall Monitor the violation reached the repo in **5 of 12** (a bcrypt dependency, a `requests` webhook, skipped tests, a reset commit, an untested change); with it, in **1 of 12** (the untested change, which Hall Monitor sent back but doesn't undo). In the other 7, plain Bob refused on its own.

**On a codebase someone else wrote** (`eval/real_repo.py`, `eval/real_repo/summary.md`): python-slugify, held to rules from its own AGENTS.md. **5 of 5** ordinary tasks verified with the tests passing, and the repo kept the project's rules in **3 of 3** tasks that asked to break them (Hall Monitor rejected the edit to the frozen legacy module; Bob refused the other two).

Across all logged runs (`eval/scorecard.md`, 91 real Bob runs): 26 of 35 attacks stopped by Hall Monitor (in the other 9 Bob refused on its own); 17 of 65 stops on work runs were later allowed, as we judged them.

Limits, plainly:
- One run per task, and one outside repository. These are counts, not rates.
- No reviewer other than the authors has used it yet, and we judged every stop ourselves.
- Hall Monitor flags work it can't verify; it doesn't undo it.
- Receipts checks Bob's claims about its work against the diff, tests and receipts. It doesn't fact-check the content of a document Bob writes.
- It relies on Bob behaviour that isn't documented (hook payload fields, MCP tool names; Bob 2.0.5 sends no PostToolUse for a failed tool call, which Hall Monitor works around) and on Jev, a model from TypeSafe.

## Run the scripted demo (no Bob needed)

```bash
pip install -r requirements.txt
python simulate.py
```

This replays a full supervised session through the real hooks and a real MCP stdio session. Open `demo/run/.hallmonitor/hall-pass.html` to see the result.

## Layout

| Path | Role |
|---|---|
| `bob/` | Bob assets: custom modes, skills, slash commands, Plan-mode rules (`scripts/install.py` copies them into a repo's `.bob/`) |
| `hm_hook.py`, `hm_mcp.py` | Entry points Bob launches (hooks, MCP server) |
| `hallmonitor/policy.py` | Decision engine: expected loss over joint outcomes, value-of-information escalation |
| `hallmonitor/questions.py` | Every Jev question |
| `hallmonitor/step.py` | Intent judgment (MCP) and enforcement (PreToolUse), including subagent checks |
| `hallmonitor/ledger.py` | Decision ledger writes: authority, supersede-never-erase |
| `hallmonitor/receipts.py` | Claim verification and the escalation ladder |
| `hallmonitor/fabricated.py` | Unknown-file check (tier 0): a claim naming a file that doesn't exist is contradicted before Jev |
| `hallmonitor/mutation.py` | Extreme mutation: finds pseudo-tested functions; runs in a scratch copy |
| `hallmonitor/lessons.py` | Cross-session lessons: saved at Stop to `.hallmonitor/lessons.json`, open the next SessionStart briefing |
| `hallmonitor/review.py` | Deep review (F3, off by default): explore-subagent reviews of the riskiest changed files |
| `hallmonitor/panels.py` | Hall Pass extra panels: Pseudo-tested, Deep review, For the next session |
| `hallmonitor/evidence.py` | Receipts ledger, checkpoints, and the stall counter |
| `hallmonitor/gitutil.py` | What changed, fresh test run, sabotage probes (scratch copy), checkpoints |
| `hallmonitor/plan.py`, `brief.py` | Certified plan gate; briefing |
| `hallmonitor/report.py` | The Hall Pass HTML report |
| `hallmonitor/bob.py` | Bob Shell: headless supervised runs and the auditor tier (`last_message`, `stats`) |
| `scripts/headless.py` | CI gate: supervised `bob run`, exit code from Receipts |
| `scripts/setup_demo.py` | Create a fresh demo repo with Hall Monitor installed, for a real Bob session |
| `scripts/probe_hook.py`, `scripts/probe_report.py`, `PROBE.md` | Probe kit for the first real-Bob session |
| `tests/` | 161 tests; no API key needed |
| `.github/workflows/tests.yml` | CI: Ubuntu + Windows, Python 3.11 + 3.13 |
| `demo/` | Demo repo template (with `docs/security-policy.pdf`) and the scripted scenario |
