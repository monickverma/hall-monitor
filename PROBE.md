# Probe: settle the unknowns in one real Bob session (≈30 min)

The Hall Monitor build has only run in simulation. Bob's docs leave these open, and a deep-research pass
(Sept 26) could not verify them:

1. The exact hook payload fields for each tool (`write_file`, `apply_diff`, `execute_command`, `spawn_subagent`)
2. Whether hooks fire for tool calls **inside subagents**, and under `bob run`
3. Whether **subagents can call MCP tools** (Hall Monitor's `declare_intent`)
4. Whether `alwaysAllow` in `.bob/mcp.json` skips MCP approval prompts
5. Where Plan mode saves its plan

Every screenshot you take here doubles as the **Bob task session evidence** the submission requires.

## Steps

1. Copy the demo repo somewhere and make it a git repo:
   ```bash
   python -c "import shutil; shutil.copytree('demo/template', 'C:/hm-probe')"
   git -C C:/hm-probe init -q
   git -C C:/hm-probe add -A
   git -C C:/hm-probe commit -qm init
   ```
2. Install the **probe** hooks. They record raw payloads and allow everything; the MCP server is installed as normal:
   ```bash
   python scripts/install.py --probe C:/hm-probe
   ```
3. Open `C:/hm-probe` in Bob as a **trusted workspace**, because hooks respect workspace trust. Take these screenshots:
   - **Settings → Hooks** showing the five hooks.
   - **Settings → MCP** showing `hall-monitor` connected with 6 tools.
4. In Agent mode, send these prompts:
   - "Create notes.txt containing 'hello'" (triggers `write_file`)
   - "Change 'hello' to 'hi' in notes.txt" (triggers `apply_diff`)
   - "Run `python -m pytest -q`" (triggers `execute_command`)
   - "Spawn an explore subagent to list the files in app/, and a general subagent that creates app/probe.py containing `X = 1`. The general subagent must first call the hall-monitor tool list_decisions with no arguments, then declare_intent with agent='sub-probe', intent='create app/probe.py', files=['app/probe.py']."
   
   Screenshot the **parallel subagents panel** and note whether you had to approve anything: MCP calls, the subagent spawn.
5. In **Plan mode**, ask for a plan to add a rate limiter. Note the path of the plan file it writes.
6. If Bob Shell is installed, run: `bob run --format json "Create notes2.txt containing 'x'" --workspace C:/hm-probe > run.json`.
7. Read the results:
   ```bash
   python scripts/probe_report.py C:/hm-probe
   ```

## What to do with the answers

| Probe result | Change in Hall Monitor |
|---|---|
| Tool input keys differ from `path` / `content` / `diff` / `command` | Add them to `hallmonitor/payload.py` (`describe`, `subagent_brief`) |
| Hooks fire inside subagents | Subagent edits are enforced per edit, too. Say so in the pitch |
| Hooks don't fire inside subagents | Nothing to change: spawn briefs and returned summaries are already checked via `spawn_subagent`. Say so in ARCHITECTURE.md |
| Subagents can call MCP (the report lists `sub-probe`) | Keep the subagent `declare_intent` protocol |
| They can't | Drop that step from `bob/custom_modes.yaml` and the protocol skill; rely on the spawn checks |
| MCP calls still asked for approval | Remove `alwaysAllow` from install.py and approve once in the demo |
| The plan file path | Add it to `plan_globs` in `hallmonitor/store.py` |

Then install for real with `python scripts/install.py C:/hm-probe` and record the demo.
