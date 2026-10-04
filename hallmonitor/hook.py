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

from . import brief, evidence, jev, lessons, payload as P, receipts, step
from .store import Store, now, rel_path

# When Jev refuses a request (HTTP 403), every hook falls back here instead of the generic error path,
# so a refusal is never silently waved through by fail_open.
REFUSED = {
    "PreToolUse": (2, "", "Hall Monitor couldn't check this action; ask the user."),
    "UserPromptSubmit": (0, "[Hall Monitor] Couldn't check this prompt, so no decisions were recorded from it. "
                            "If it states a rule, ask the user to confirm it and record it with record_decision.", ""),
    "SessionStart": (0, "[Hall Monitor] Couldn't read the rules in AGENTS.md at session start. Ask the user "
                        "which rules apply, and record them with record_decision.", ""),
}

def stop(p, store):
    """Bob's final answer is kept (answers.jsonl, shown in the Hall Pass), then the backstop for unsubmitted work, then
    this session's lessons for the next one (lessons.py). Bob's Stop payload carries last_assistant_message."""
    answer = P.assistant_text(p)
    if answer:
        store._append("answers.jsonl", {"ts": now(), "goal": store.session().get("goal"), "answer": answer[:8000]})
    result = receipts.stop_hook(store, answer)
    lessons.save(store)
    return result


HANDLERS = {
    "SessionStart": brief.session_start,
    "UserPromptSubmit": brief.user_prompt,
    "PreToolUse": step.pre_tool,
    "PostToolUse": step.post_tool,
    "Stop": stop,
}


def repo_root(cwd):
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True)
    return Path(r.stdout.strip() or cwd)


def handle(payload):
    store = Store(repo_root(payload.get("cwd") or os.getcwd()))
    handler = HANDLERS.get(P.event(payload))
    if handler is None:
        return 0, "", ""
    # One hook event at a time: Bob's parallel tool calls each start a hook process, and their reads and writes of the
    # session, the evidence ledger and the event log must not interleave (store.Store.locked).
    try:
        with store.locked(timeout=50):
            return _handle(payload, store, handler)
    except TimeoutError:
        if store.config()["fail_open"]:
            return 0, "", ""
        return 2, "", "Hall Monitor could not check this action (its store stayed locked); blocking because fail_open is off."


def _handle(payload, store, handler):
    try:
        if P.event(payload) in ("Stop", "UserPromptSubmit"):  # the turn is over: nothing is still running
            evidence.settle_pending(store)
        try:
            code, out, err = handler(payload, store)
        except jev.JevRefused:
            store.log({"stage": "error", "event": P.event(payload), "fallback": "jev_refused",
                       "error": "Jev refused the request"})
            if P.event(payload) == "Stop":
                store.queue_note("Hall Monitor couldn't check the final claims. Ask the user to review them.")
                from . import report
                report.write_hall_pass(store)
            code, out, err = REFUSED.get(P.event(payload), (0, "", ""))
        if code == 2 and err:
            path, command, _ = P.describe(P.tool(payload), P.tool_input(payload))
            # repo-relative, like everywhere else: Bob's edit tools send absolute paths
            target = rel_path(store.root, path, base=P.first(payload, "cwd")) if path else command or P.tool(payload)
            store.record_block(P.tool(payload), target, err)
            lines = err.splitlines()
            reason = next((l[2:] for l in lines if l.startswith("- ")), lines[0])
            store.queue_note(f"Blocked {P.tool(payload)} on {target}: {reason[:200]} "
                             "(call explain_block for the full reason)")
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
    # Bob sends UTF-8. Read as bytes: on Windows, text-mode stdin uses the ANSI code page, and real Bob, Oct 4, had
    # its final answer "VERIFIED — RECEIPTS" arrive as "VERIFIED â€” RECEIPTS" (prompts and edits too).
    raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    code, out, err = handle(json.loads(raw) if raw.strip() else {})
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    sys.exit(code)


if __name__ == "__main__":
    main()
