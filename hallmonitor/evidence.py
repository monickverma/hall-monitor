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

from . import gitutil, payload as P
from .store import rel_path

FAIL = re.compile(r"\b\d+ (failed|errors?)\b|^FAILED\b|^ERROR\b|Traceback \(most recent call last\)|"
                  r"npm ERR!|command not found|is not recognized as an internal or external command|"
                  r"No such file or directory|can't open file", re.M)
PASS = re.compile(r"\b\d+ passed\b")
TEST_CMD = re.compile(r"^\s*((python3?|py)\s+-m\s+)?pytest\b|^\s*(npm|yarn|pnpm)\s+(run\s+)?test\b")
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


def is_test_command(command, cfg):
    c = (command or "").strip()
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


def record(p, store):
    """PostToolUse on an edit or a command: append a receipt and update the evidence signals."""
    cfg, sess = store.config(), store.session()
    tool = P.tool(p)
    path, command, _ = P.describe(tool, P.tool_input(p))
    if tool in P.EDIT_TOOLS and path:
        rel = rel_path(store.root, path, base=P.first(p, "cwd"))
        sess["edit_seq"] += 1
        store.add_evidence({"kind": "edit", "file": rel, "tool": tool, "edit_seq": sess["edit_seq"]})
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
    status, source = outcome(out, P.exit_code(p))
    kind = "test" if is_test_command(command, cfg) else "command"
    row = store.add_evidence({"kind": kind, "command": command, "status": status, "status_source": source,
                              "tail": out[-800:], "sha1": hashlib.sha1(out.encode("utf-8")).hexdigest()[:12],
                              "edit_seq": sess["edit_seq"]})
    sess["commands"].append({"command": command, "output": out[-800:]})
    if kind == "test":
        sess["edits_since_test"] = 0
    line = last_line(out)
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
