"""Bob Shell integration (`bob run`, non-interactive).

`bob run --format json` returns one object with `status`, `last_message` and `stats` (task_id, token
counts, duration_ms, session_costs, tool_calls). Under `bob run` every tool is pre-approved, so no
human approves anything: Hall Monitor's hooks and the no-edit auditor mode are the only gate.
Bob Shell reads its key from BOB_API_KEY. HM_BOB_ACCEPT_LICENSE=1 and HM_BOB_TEAM_ID=<id> are opt-ins for a
fresh machine; a failure before the task runs comes back as status "unparsed" with Bob's `error`.
"""
import json
import os
import shutil
import subprocess
import time


def _run(root, mode, prompt, max_cost, max_turns, timeout):
    if os.environ.get("HM_DISABLE_BOB_SHELL") or not shutil.which("bob"):
        return None
    cmd = ["bob", "run", "--mode", mode, "--format", "json", "--max-cost", str(max_cost),
           "--max-turns", str(max_turns), "--workspace", str(root)]
    # On a fresh machine (a CI runner) `bob run` stops at IBM's license, and a "general" API key needs a
    # team id. Both are the operator's to give: Hall Monitor never accepts the license on its own.
    if os.environ.get("HM_BOB_ACCEPT_LICENSE"):
        cmd.append("--accept-license")
    if os.environ.get("HM_BOB_TEAM_ID"):
        cmd += ["--team-id", os.environ["HM_BOB_TEAM_ID"]]
    cmd.append(prompt)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"status": "unparsed", "last_message": r.stdout[-3000:], "stats": {}, "exit_code": r.returncode,
                "error": (r.stderr or "").strip()[-1000:]}
    data["exit_code"] = r.returncode
    return data


def _record(root, mode, prompt, data):
    from .store import Store
    store = Store(root)
    stats = data.get("stats") or {}
    store._append("bob_runs.jsonl", {"t": time.time(), "mode": mode, "prompt": prompt[:300],
                                     "status": data.get("status"), "stats": stats})
    store.log({"stage": "bob_run", "action": data.get("status") or "done", "target": f"bob run --mode {mode}",
               "bob_stats": {k: stats.get(k) for k in ("session_costs", "tool_calls", "total_tokens", "duration_ms")
                             if k in stats}})


def shell_audit(root, brief, max_cost="0.30", max_turns="8", timeout=240):
    """Audit one claim with the read-only Receipts Auditor mode. Returns the auditor's final message."""
    data = _run(root, "hm-auditor", brief, max_cost, max_turns, timeout)
    if not data:
        return None
    _record(root, "hm-auditor", brief, data)
    return str(data.get("last_message") or "")[:3000] or None


def run_supervised(root, task, max_cost="2.00", max_turns="60", timeout=1800):
    """Headless supervised run (CI): Bob works in the Supervised mode; Hall Monitor's hooks gate it."""
    data = _run(root, "supervised", task, max_cost, max_turns, timeout)
    if data:
        _record(root, "supervised", task, data)
    return data
