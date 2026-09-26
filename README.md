# Hall Monitor for IBM Bob

**Trust Bob's work without re-checking it.**
- **Rules:** Bob reads the rules from your policy documents, and Hall Monitor enforces them on every action it takes, including on parallel subagents.
- **Rationalizations:** it names them ("just this once…") and rejects them before anything runs.
- **Receipts:** every claim Bob makes about its work comes back with receipts: the diff, a fresh test run, and sabotage probes that prove the tests actually check the code.

TypeSafe's Jev makes every judgment in one cheap parallel call. Uncertain cases escalate to a read-only Bob auditor subagent, and only then to you. A whole supervised session costs about $0.003 of Jev.

See [ARCHITECTURE.md](ARCHITECTURE.md) for how each Bob feature is used and the decision flow.

## Use it with Bob

```bash
python scripts/install.py path/to/your/repo
```

Then:
1. Open the repo as a **trusted** workspace (hooks respect workspace trust), check **Settings → Hooks** lists the five hooks, and approve the `hall-monitor` MCP server.
2. Switch to the **🛂 Supervised** mode.
3. Run `/decisions docs/your-policy.pdf`.
4. Give Bob the task. Bob declares intents, Hall Monitor judges them, and hooks enforce them.
5. When Bob is done, it calls `submit_claims`, fixes whatever comes back unverified, and finishes with `/hall-pass` (Bob publishes the report with `create_html_artifact`). `/export-ledger docs/ledger.xlsx` writes the decisions and receipts to Excel with Bob's `office_edit`.

This installs, under `.bob/`: hooks (`settings.json`), the MCP server (`mcp.json`), two custom modes, four skills, five slash commands, and Plan-mode rules.

**First time in real Bob?** Run the 30-minute probe in [PROBE.md](PROBE.md) first. It settles the behaviors Bob's docs leave open, and its screenshots double as the required Bob task evidence.

**CI / headless:** `python scripts/headless.py <repo> "<task>"` runs Bob Shell (`bob run --mode supervised --format json`) and exits non-zero unless Receipts verified the work. Under `bob run` every tool is pre-approved, so Hall Monitor is the only gate. `TYPESAFE_API_KEY` must be in the environment Bob runs in. Never commit it.

## Run the scripted demo (no Bob needed)

```bash
pip install typesafe-sdk pytest reportlab
python simulate.py
```

This replays a full supervised session through the real hooks and a real MCP stdio session. Open `demo/run/.hallmonitor/hall-pass.html` to see the result.

## Layout

| Path | Role |
|---|---|
| `bob/` | Bob assets: custom modes, skills, slash commands, Plan-mode rules |
| `hm_hook.py`, `hm_mcp.py` | Entry points Bob launches (hooks, MCP server) |
| `hallmonitor/policy.py` | Decision engine: expected loss over joint outcomes, value-of-information escalation |
| `hallmonitor/questions.py` | Every Jev question |
| `hallmonitor/step.py` | Intent judgment (MCP) and enforcement (PreToolUse), including subagent checks |
| `hallmonitor/ledger.py` | Decision ledger writes: authority, supersede-never-erase |
| `hallmonitor/receipts.py` | Claim verification and the escalation ladder |
| `hallmonitor/plan.py`, `brief.py` | Certified plan gate; briefing |
| `hallmonitor/report.py` | The Hall Pass HTML report |
| `hallmonitor/bob.py` | Bob Shell: headless supervised runs and the auditor tier (`last_message`, `stats`) |
| `scripts/headless.py` | CI gate: supervised `bob run`, exit code from Receipts |
| `scripts/probe_hook.py`, `scripts/probe_report.py`, `PROBE.md` | Probe kit for the first real-Bob session |
| `demo/` | Demo repo template (with `docs/security-policy.pdf`) and the scripted scenario |
