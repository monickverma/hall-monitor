"""Bob hook entry point: `python -m hallmonitor.hook` reads one JSON payload on stdin.

Exit code 2 blocks (PreToolUse / UserPromptSubmit only). Per Bob's docs, stderr goes to Bob's logs,
not to the model, so every block reason is also kept for the explain_block MCP tool and queued for
the next prompt's context (SessionStart / UserPromptSubmit stdout is the only hook output Bob reads).
"""
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

from . import brief, payload as P, receipts, step
from .store import Store

HANDLERS = {
    "SessionStart": brief.session_start,
    "UserPromptSubmit": brief.user_prompt,
    "PreToolUse": step.pre_tool,
    "PostToolUse": step.post_tool,
    "Stop": lambda p, s: receipts.stop_hook(s, P.assistant_text(p)),
}


def repo_root(cwd):
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True)
    return Path(r.stdout.strip() or cwd)


def handle(payload):
    store = Store(repo_root(payload.get("cwd") or os.getcwd()))
    handler = HANDLERS.get(P.event(payload))
    if handler is None:
        return 0, "", ""
    try:
        code, out, err = handler(payload, store)
        if code == 2 and err:
            path, command, _ = P.describe(P.tool(payload), P.tool_input(payload))
            target = path or command or P.tool(payload)
            store.record_block(P.tool(payload), target, err)
            store.queue_note(f"Blocked {P.tool(payload)} on {target}: " + err.splitlines()[0][:200] +
                             " (call explain_block for the full reason)")
        return code, out, err
    except Exception as e:  # supervision must never brick the agent unless configured to
        store.log({"stage": "error", "event": P.event(payload), "error": repr(e),
                   "trace": traceback.format_exc()[-1500:]})
        if store.config()["fail_open"]:
            return 0, "", ""
        return 2, "", f"Hall Monitor could not check this action ({e}); blocking because fail_open is off."


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    raw = sys.stdin.read()
    code, out, err = handle(json.loads(raw) if raw.strip() else {})
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    sys.exit(code)


if __name__ == "__main__":
    main()
