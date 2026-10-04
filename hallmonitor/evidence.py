"""The evidence ledger (receipts), checkpoints and the stall counter.

PostToolUse sees every edit and command Bob makes. Each one becomes a numbered receipt in
.hallmonitor/evidence.jsonl (E1, E2, ...):
- Receipts requires claims to cite these IDs, and checks them in code before Jev is asked.
- A passing test run becomes a git checkpoint (refs/hallmonitor/C<n>), a state Bob can return to.
- Evidence signals feed a stall counter. Each stall names its pattern; past the limit, Hall Monitor
  stops and asks the user, with a restart plan.

PostToolUse can't talk to Bob, so everything noticed here is queued as a note. The note reaches Bob at
the top of the next MCP result, or in the next prompt's briefing.
"""
import hashlib
import re
from pathlib import Path

from . import gitutil, payload as P
from .store import rel_path

FAIL = re.compile(r"\b\d+ (failed|errors?)\b|^FAILED\b|^ERROR\b|Traceback \(most recent call last\)|"
                  r"npm ERR!|command not found|is not recognized as an internal or external command|"
                  r"No such file or directory|can't open file", re.M)
PASS = re.compile(r"\b\d+ passed\b")
TEST_CMD = re.compile(r"^\s*((python3?|py)\s+-m\s+)?pytest\b|^\s*(npm|yarn|pnpm)\s+(run\s+)?test\b")
COLLECT_ONLY = re.compile(r"\s--co(llect-only)?\b")
CODE_EXT = (".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".rs", ".cs", ".php", ".kt",
            ".swift", ".c", ".cc", ".cpp", ".h")


def outcome(output, exit_code=None):
    """(status, source): pass / fail / unknown. From the exit code if Bob sends one, else from the output."""
    if exit_code is not None:
        return ("pass" if exit_code == 0 else "fail"), "exit_code"
    if FAIL.search(output or ""):
        return "fail", "inferred"
    if PASS.search(output or ""):
        return "pass", "inferred"
    return "unknown", "inferred"


CD_PREFIX = re.compile(r"""^\s*cd\s+(?:"([^"]+)"|'([^']+)'|(\S+))\s*(?:&&|;)\s*""")


def repo_command(root, command):
    """The command as it runs in the repo. Real Bob Shell on Linux, Sept 27: Bob runs `cd <workspace> && python
    -m pytest ...`, so no test run counted as a test receipt and no command matched its declared intent. A
    leading `cd` into the repo (or a folder inside it) is dropped; a `cd` anywhere else is kept."""
    m = CD_PREFIX.match(command or "")
    if not m:
        return command
    d = next(g for g in m.groups() if g)
    root = Path(root).resolve()
    target = (Path(d) if Path(d).is_absolute() else root / d).resolve()
    return command[m.end():] if target == root or root in target.parents else command


def is_test_command(command, cfg):
    c = (command or "").strip()
    if COLLECT_ONLY.search(c):  # real Bob, Sept 27: `pytest --collect-only` counts tests but runs none
        return False
    return c.startswith(cfg["test_command"].strip()) or bool(TEST_CMD.match(c))


def is_code(path):
    return str(path).lower().endswith(CODE_EXT)


def last_line(output):
    lines = [l.strip() for l in (output or "").splitlines() if l.strip()]
    return lines[-1][:200] if lines else ""


def last_code_edit_seq(rows):
    """edit_seq of the newest edit to a code or test file (0 if none)."""
    return max((r["edit_seq"] for r in rows if r["kind"] == "edit" and is_code(r.get("file", ""))), default=0)


def checkpoints(rows):
    return [r for r in rows if r["kind"] == "checkpoint"]


def _note(sess, text):
    if text not in sess["notes"]:
        sess["notes"].append(text)


def stall(store, sess, pattern, detail):
    """One more stall: queue a re-brief that names the pattern (not a generic "refocus")."""
    sess["stalls"] += 1
    rules = "; ".join(f"{d['id']}: {d['text']}" for d in store.active_decisions())
    _note(sess, f"Stall {sess['stalls']} ({pattern}): {detail}. Goal: {sess.get('goal') or 'the user request'}"
                + (f" Active rules: {rules}" if rules else ""))
    store.log({"stage": "stall", "action": "flag", "pattern": pattern, "target": detail, "stalls": sess["stalls"]})


CYCLE_WINDOW = 6


def repeating_unit(keys, window=CYCLE_WINDOW):
    """The 2- or 3-step sequence the last `window` steps repeat, or None. A 1-step repeat is left to
    "looping on one failure" and "editing without testing"."""
    last = keys[-window:]
    if len(last) < window:
        return None
    for n in (2, 3):
        unit = last[-n:]
        if window % n == 0 and len(set(unit)) > 1 and last == unit * (window // n):
            return unit
    return None


def _circling(store, sess, key, label):
    """v4.2 cycle-rate signal: the same edits (same content) and commands (same outcome) in a loop.
    An edit-test cycle that makes progress changes the edit content or the test outcome, so it never
    repeats exactly."""
    steps = (sess.get("cycle") or []) + [[key, label]]
    unit = repeating_unit([k for k, _ in steps])
    if unit:
        names = [lbl for k, lbl in steps[-len(unit):]]
        stall(store, sess, "going in circles",
              f"the last {CYCLE_WINDOW} steps repeat the same {len(unit)} steps ({' -> '.join(names)})")
        steps = []
    sess["cycle"] = steps[-2 * CYCLE_WINDOW:]


# Bob 2.0.5 calls no PostToolUse hook when a tool call ends in error (bob.js, onToolResult: `isError || PostToolUse`),
# so a failed command never reported back. In every real run up to Oct 4 there was no failed-command receipt, and the
# outcome check (T2: the next intent must deal with a failure) never fired. PreToolUse always fires and PostToolUse
# fires for every success, so a command that was allowed and never reported back ended in error.
NO_POST_TOOL_USE = ("(no output: this command never reported back, and Bob calls no PostToolUse hook when a tool "
                    "call ends in error, so it is recorded as failed)")


def note_pending(store, p, agent):
    """PreToolUse allowed a command: keep it until its PostToolUse arrives."""
    sess = store.session()
    _, command, _ = P.describe(P.tool(p), P.tool_input(p))
    key = P.first(p, "tool_use_id") or f"{command}|{len(sess['pending_commands'])}"
    sess["pending_commands"][key] = {"tool": P.tool(p), "command": command, "cwd": P.first(p, "cwd"), "agent": agent}
    store.save_session(sess)


def clear_pending(store, p):
    """PostToolUse: the command reported back. Without a tool_use_id, the oldest entry for the same command."""
    sess = store.session()
    pending, key = sess["pending_commands"], P.first(p, "tool_use_id")
    if key not in pending:
        _, command, _ = P.describe(P.tool(p), P.tool_input(p))
        key = next((k for k, v in pending.items() if v["command"] == command), None)
    if key is not None:
        pending.pop(key, None)
        store.save_session(sess)


def settle_pending(store, agent=None):
    """Record as failed each pending command that never reported back: every one when `agent` is None, else only that
    agent's own (another agent's command may still be running). A command allowed while subagents were running
    belongs to no known agent, and is settled only once none is running."""
    sess = store.session()
    pending = sess["pending_commands"]
    mine = [k for k, v in pending.items()
            if agent is None or v["agent"] == agent or (v["agent"] is None and not sess["running_subagents"])]
    if not mine:
        return
    failed = [pending.pop(k) for k in mine]
    store.save_session(sess)
    for v in failed:
        record({"tool_name": v["tool"], "tool_input": {"command": v["command"]}, "cwd": v["cwd"],
                "tool_response": {"content": NO_POST_TOOL_USE, "exit_code": 1}}, store,
               source="no PostToolUse (Bob skips it for a failed tool call)")


def record(p, store, source=None):
    """PostToolUse on an edit or a command: append a receipt and update the evidence signals."""
    cfg, sess = store.config(), store.session()
    tool = P.tool(p)
    path, command, detail = P.describe(tool, P.tool_input(p))
    command = repo_command(store.root, command)
    if tool in P.EDIT_TOOLS and path:
        rel = rel_path(store.root, path, base=P.first(p, "cwd"))
        sess["edit_seq"] += 1
        store.add_evidence({"kind": "edit", "file": rel, "tool": tool, "edit_seq": sess["edit_seq"]})
        _circling(store, sess, f"edit {rel} {hashlib.sha1(detail.encode('utf-8')).hexdigest()[:10]}", f"edit {rel}")
        if is_code(rel):
            sess["edits_since_test"] += 1
            if sess["edits_since_test"] == cfg["max_edits_without_test"]:
                stall(store, sess, "editing without testing",
                       f"{sess['edits_since_test']} code edits since the last test run")
        store.save_session(sess)
        return
    if not command:
        return
    out = P.tool_output(p)
    status, inferred = outcome(out, P.exit_code(p))
    kind = "test" if is_test_command(command, cfg) else "command"
    row = store.add_evidence({"kind": kind, "command": command, "status": status, "status_source": source or inferred,
                              "tail": out[-800:], "sha1": hashlib.sha1(out.encode("utf-8")).hexdigest()[:12],
                              "edit_seq": sess["edit_seq"]})
    sess["commands"].append({"command": command, "output": out[-800:]})
    if kind == "test":
        sess["edits_since_test"] = 0
    line = last_line(out)
    _circling(store, sess, f"run {command.strip()} {status} {line}", f"`{command.strip()[:60]}`")
    rows = store.evidence()
    cps = checkpoints(rows)

    if status == "fail":
        key = f"{command.strip()} -> {line}"
        sess["fail_repeats"][key] = sess["fail_repeats"].get(key, 0) + 1
        note = (f"Your last command failed: `{command}` -> {line}. "
                "Your next declare_intent must say how you'll handle it.")
        if kind == "test" and cps and sess["regression_seen"] != cps[-1]["checkpoint"]:
            cp = cps[-1]
            sess["regression_seen"] = cp["checkpoint"]
            note = (f"Tests passed at checkpoint {cp['checkpoint']} ({cp['from']}) and now fail: {line}. "
                    f"Your next declare_intent must fix this or restore {cp['checkpoint']}.")
            stall(store, sess, "breaking a passing state", f"tests passed at {cp['checkpoint']} and now fail")
        elif sess["fail_repeats"][key] >= 2:
            stall(store, sess, "looping on one failure",
                   f"`{command}` failed the same way {sess['fail_repeats'][key]} times")
        sess["failed_step"] = {"id": row["id"], "command": command, "last_line": line}
        _note(sess, note)
    elif status == "pass" and kind == "test":
        sess["failed_step"] = None
        n = len(cps) + 1
        cp = gitutil.checkpoint(store.root, n, last_tree=cps[-1].get("tree") if cps else None)
        if cp:
            store.add_evidence({"kind": "checkpoint", "checkpoint": f"C{n}", "ref": cp["ref"],
                                "commit": cp["commit"], "tree": cp["tree"], "from": row["id"],
                                "edit_seq": sess["edit_seq"]})
            sess["stalls"], sess["fail_repeats"], sess["regression_seen"] = 0, {}, None
    store.save_session(sess)


def restart_plan(store):
    """At the stall limit: the checkpoint to restore, the interrupted work saved as an optional overlay."""
    cps = checkpoints(store.evidence())
    if not cps:
        return ("No passing checkpoint exists yet. Ask the user whether to continue, or to restart the task "
                "with a fresh subagent and a narrower brief.")
    cp = cps[-1]
    overlay = store.dir / "overlay.diff"
    overlay.write_text(gitutil.diff_from(store.root, cp["ref"]), encoding="utf-8")
    return (f"Restore checkpoint {cp['checkpoint']} (made from passing test run {cp['from']}): "
            f"`git stash push -u -m hm-before-restore`, then `git checkout {cp['ref']} -- .`. "
            "Then start a fresh subagent with the task brief. The interrupted diff is saved in "
            ".hallmonitor/overlay.diff to inspect, apply or discard.")


def describe(row):
    """One line per receipt, for list_evidence."""
    if row["kind"] == "edit":
        return f"{row['id']} edit {row['file']} (#{row['edit_seq']})"
    if row["kind"] == "checkpoint":
        return f"{row['id']} checkpoint {row['checkpoint']} (from {row['from']})"
    summary = PASS.search(row.get("tail", "")) or re.search(r"\b\d+ failed\b", row.get("tail", ""))
    status = row["status"].upper() + (f" ({summary[0]})" if summary else "")
    return f"{row['id']} {row['kind']} \"{row['command']}\" {status} after edit #{row['edit_seq']}"


def list_evidence(store, limit=40):
    rows = store.evidence()
    if not rows:
        return "No receipts yet. Edits and commands you run are recorded here as E1, E2, ..."
    lines = [describe(r) for r in reversed(rows[-limit:])]
    return ("Receipts, newest first. Cite the IDs that prove each claim; for claims about tests, cite a "
            "test run made after your last edit.\n" + "\n".join(lines))
