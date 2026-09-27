"""DURING: judge declared intents (MCP declare_intent) and every tool call before it runs (PreToolUse).

Bob's hook payload carries only {tool, input}, never the agent's reasoning. So the Supervised mode
makes Bob declare its intent through the Hall Monitor MCP tool first. That call is judged
immediately and the verdict goes straight back to Bob as the tool result (hooks can't talk back).
PreToolUse then enforces it: no covering intent means no edit, a rejected intent stays rejected,
and an edit that does something other than what was declared is blocked.
"""
import fnmatch
import re
import sys
import time
from pathlib import Path

from . import evidence, gitutil, jev, payload as P, policy, questions as Q
from .store import is_protected, rel_path


MAX_EDIT_CHARS = 6000  # about 1,500 Jev input tokens, well under a cent per thousand edits

# A rule against new dependencies is settled in code where code can tell: a command that installs nothing, and an
# edit whose imports are all standard library, the repo's own or already imported in the repo, add none. Real Bob,
# Sept 27: `python -m pytest -q` (p=0.26, 0.22) and a test edit (p=0.32) went to the user as possible breaks of
# "Do not add third-party dependencies". Anything else (an install, a manifest, another import) stays Jev's.
DEPENDENCY_RULE_RE = re.compile(r"third[- ]party|dependenc(y|ies)|standard library|\bstdlib\b", re.I)
INSTALL_RE = re.compile(r"\b(install|add|develop)\b", re.I)
MANIFEST_RE = re.compile(r"requirements[\w.-]*\.(txt|in)|pyproject\.toml|setup\.(py|cfg)|pipfile|poetry\.lock|"
                         r"package(-lock)?\.json|environment\.ya?ml", re.I)
DOC_FILES = (".md", ".rst")


def _imports(text):
    """Top-level module names a piece of Python (or a diff of it) imports; relative imports are the repo's."""
    mods = set()
    for line in (text or "").splitlines():
        s = re.sub(r"^[\s+>-]*", "", line)
        m = re.match(r"from\s+(\.*)([\w.]*)\s+import\b", s)
        if m:
            if not m[1]:
                mods.add(m[2].split(".")[0])
            continue
        m = re.match(r"import\s+([^#;]+)", s)
        for part in (m[1].split(",") if m else []):
            name = (part.split() or [""])[0].split(".")[0]
            mods.add(name)
    return mods


def _repo_modules(root, limit=2000):
    """Modules the repo already has or imports: its top-level folders and files, its .py files' names, and every
    module its tracked .py files import."""
    known = set()
    for f in gitutil.tracked_files(root)[:limit]:
        top = f.split("/")[0]
        known.add(top[:-3] if top.endswith(".py") else top)
        if f.endswith(".py"):
            known |= {Path(f).stem} | _imports(_read(root, f, 200000))
    return known


def adds_no_dependency(root, action):
    """True when code can tell that `action` adds no dependency: see DEPENDENCY_RULE_RE."""
    if "declared_intent" in action:  # an intent's files are edited later, and each edit is checked then
        cmds = action.get("commands") or []
        return bool(cmds) and not action.get("files") and \
            not any(INSTALL_RE.search(c) or MANIFEST_RE.search(c) for c in cmds)
    target, tool = str(action.get("target") or ""), action.get("tool")
    if tool in P.COMMAND_TOOLS:
        return bool(target) and not (INSTALL_RE.search(target) or MANIFEST_RE.search(target))
    if tool not in P.EDIT_TOOLS or not target or MANIFEST_RE.search(target):
        return False
    if target.lower().endswith(DOC_FILES):
        return True
    if not target.endswith(".py"):
        return False
    new = {m for m in _imports(action.get("content")) if m and m not in sys.stdlib_module_names and m != "__future__"}
    return not new or new <= _repo_modules(root)

def _read(root, path, limit=3000):
    try:
        return (Path(root) / path).read_text(encoding="utf-8")[:limit]
    except (OSError, UnicodeDecodeError, TypeError):
        return None


def judge(store, action, reason=None, check_match=False, agent="main", agent_task=None, deep=False,
          failed_step=None):
    """One parallel Jev request over everything that matters for this action, then minimum expected loss.

    With `failed_step` (a command that just failed), the same request also asks whether the stated
    reason deals with that failure (the outcome check)."""
    cfg, sess = store.config(), store.session()
    decisions = store.active_decisions(kind="limit")  # obligations are checked by Receipts
    others = [{"agent": it["agent"], "task": it.get("agent_task"), "intent": it["intent"],
               "files": it.get("files", [])} for it in store.active_intents(exclude_agent=agent)][-4:]
    if deep and action.get("target"):
        action = {**action, "current_file_before_change": _read(store.root, action["target"])}
    state = {
        "goal": sess.get("goal") or "(no goal recorded yet)",
        "agent": {"name": agent, "assigned_task": agent_task} if agent != "main" else None,
        "decisions": {d["id"]: d["text"] for d in decisions},
        "recent_actions": sess["actions"][-(10 if deep else 5):],
        "other_agents": others,
        "action": action,
        "stated_reason": reason or None,
    }
    ids = [d["id"] for d in decisions]
    # An edit under an approved intent (check_match) was already judged on-task and clash-free when the
    # intent was approved. Asking again only adds noise: in the scripted demo, several small readings
    # (mismatch 0.20, clash 0.14, ...) added up to a false block. At edit time the questions are whether the
    # edit does what was declared, and whether its content is destructive or breaks a rule.
    questions = Q.step(ids, bool(reason), check_match, 0 if check_match else len(others))
    if check_match:
        questions.pop("on_task")
    if failed_step and reason:
        state["last_failed_step"] = failed_step
        questions["handles_failure"] = Q.HANDLES_FAILURE
    answers, usage = jev.ask(state, questions)
    viol = {d: answers[f"violates_{d}"]["noul"] for d in ids}
    dependency_rules = [d["id"] for d in decisions if DEPENDENCY_RULE_RE.search(d["text"])]
    if dependency_rules and adds_no_dependency(store.root, action):
        viol.update({d: 0.0 for d in dependency_rules})
    risks = {
        "destructive": answers["destructive"]["noul"],
        # max, not noisy-or: many weak, correlated guesses must not add up to a confident violation
        "violates": max(viol.values(), default=0.0),
    }
    if "on_task" in answers:
        risks["off_task"] = jev.p_levels(answers["on_task"], [0, 1])
    pattern = None
    if "rationalization" in answers:
        dist = answers["rationalization"]["probabilities"]
        risks["rationalizing"] = 1 - dist.get("none", 0.0)
        pattern = max((k for k in dist if k != "none"), key=dist.get)
    if "matches_intent" in answers:
        risks["mismatch"] = 1 - answers["matches_intent"]["noul"]
    conflicts = {others[j]["agent"]: answers[f"conflict_{j}"]["noul"] for j in range(len(others))
                 if f"conflict_{j}" in answers}  # not asked for an edit under an approved intent
    if conflicts:
        risks["conflict"] = max(conflicts.values())
    worlds, reveal = policy.independent(risks, tuple(cfg["uncertain_band"]))
    cost = cfg["human_cost"] if deep else cfg["escalate_cost"]
    d = policy.decide(worlds, reveal, policy.STEP_HARM, escalate_cost=cost, risks=risks)
    detail = {"violations": viol, "pattern": pattern, "conflicts": conflicts, "tokens": jev.tokens(usage)}
    if "handles_failure" in answers:
        detail["handles_failure"] = answers["handles_failure"]["noul"]
    if d.escalate and not deep:  # a closer look with full context is worth its cost
        d2, detail2 = judge(store, action, reason, check_match, agent, agent_task, deep=True,
                            failed_step=failed_step)
        detail2["tokens"] += detail["tokens"]
        detail2["escalated"] = "deep_look"
        if d2.escalate:
            d2.action, detail2["escalated"] = "ask_human", "human"
        return d2, detail2
    return d, detail


def explain(store, d, detail):
    r = d.risks
    lines = []
    texts = {x["id"]: x["text"] for x in store.active_decisions()}
    ranked = sorted(detail["violations"].items(), key=lambda kv: -kv[1])
    for did, p in ranked:
        if p >= 0.5 or (p >= 0.25 and did == ranked[0][0]):
            lines.append(f"- may break {did} \"{texts.get(did, '')}\" (p={p:.2f})")
    if r.get("destructive", 0) >= 0.25:
        lines.append(f"- destructive / hard to undo (p={r['destructive']:.2f})")
    if r.get("rationalizing", 0) >= 0.5:
        lines.append(f"- the stated reason reads as a rationalization: {detail['pattern']} (p={r['rationalizing']:.2f})")
    if r.get("mismatch", 0) >= 0.5:
        lines.append(f"- the edit does something other than the declared intent (p={r['mismatch']:.2f})")
    others = {it["agent"]: it["intent"] for it in store.active_intents()}
    for agent, p in detail.get("conflicts", {}).items():
        if p >= 0.3:
            lines.append(f"- {'conflicts' if p >= 0.5 else 'may overlap'} with parallel work by {agent} "
                         f"(p={p:.2f}): \"{others.get(agent, '')[:120]}\" (coordinate before editing)")
    if r.get("off_task", 0) >= 0.5:
        lines.append(f"- not needed for the current goal (p={r['off_task']:.2f})")
    if not lines:  # no single risk is likely, but together they are too uncertain to wave through
        top = sorted(((p, k) for k, p in r.items() if p >= 0.1), reverse=True)[:3]
        lines.append("- uncertain: " + ", ".join(f"{k.replace('_', ' ')} p={p:.2f}" for p, k in top))
    return "\n".join(lines)


VERDICT = {"allow": "approved", "rebrief": "approved_with_note", "block": "rejected", "ask_human": "ask_human"}


def declare_intent(store, intent, files=(), commands=(), agent="main", agent_task=None):
    """MCP tool: judge a plan of action before any tool runs; the answer goes straight back to Bob.
    (Pending notes and flags are put in front of every MCP result by the MCP server.)"""
    t0 = time.time()
    cfg, sess = store.config(), store.session()
    files = [rel_path(store.root, f) for f in files or []]
    commands = [evidence.repo_command(store.root, c) for c in commands or []]
    target = ", ".join(files + commands)
    base = {"agent": agent, "agent_task": agent_task, "intent": intent, "files": files, "commands": commands}

    if sess["stalls"] > cfg["stall_limit"]:  # the stall counter passed its limit: stop and ask the user
        why = (f"- {sess['stalls']} stalls since the last passing checkpoint (the limit is {cfg['stall_limit']}).\n"
               f"- Restart plan for the user: {evidence.restart_plan(store)}")
        row = store.add_intent({**base, "verdict": "ask_human", "why": why})
        store.log({"stage": "intent", "agent": agent, "target": target, "reason": intent[:300],
                   "action": "ask_human", "verdict": "ask_human", "note": "stall limit",
                   "ms": int((time.time() - t0) * 1000)})
        return f"{row['id']} needs the user's decision before you continue:\n{why}\nAsk the user."

    if commands and not files and not sess["failed_step"] and all(re.match(cfg["safe_commands"], c) for c in commands):
        # Only safe commands (the test command, git status, ...), which PreToolUse allows without Jev anyway.
        # Real Bob, Sept 27: Jev was unsure about "run python -m pytest -q", so Bob stopped to ask the user.
        row = store.add_intent({**base, "verdict": "approved", "why": ""})
        store.log({"stage": "intent", "agent": agent, "target": target, "reason": intent[:300], "action": "allow",
                   "verdict": "approved", "note": "safe commands only", "ms": int((time.time() - t0) * 1000)})
        return f"{row['id']} approved. Go ahead: {target}."

    failed = sess["failed_step"]
    suspect = [f for f in files if f in sess["suspect_files"]]  # v4 loop L4 -> L1
    try:
        action = {"declared_intent": intent, "files": files, "commands": commands}
        if suspect:  # the deep look, with the suspect files as they are now
            action["current_files_before_change"] = {f: _read(store.root, f) for f in suspect[:3]}
        d, detail = judge(store, action, reason=intent, agent=agent, agent_task=agent_task, failed_step=failed,
                          deep=bool(suspect))
    except jev.JevRefused:
        row = store.add_intent({**base, "verdict": "ask_human", "why": "- Hall Monitor couldn't check this intent."})
        store.log({"stage": "intent", "agent": agent, "target": target, "reason": intent[:300],
                   "action": "ask_human", "verdict": "ask_human", "fallback": "jev_refused"})
        return f"{row['id']}: Hall Monitor couldn't check this; ask the user."
    verdict = VERDICT[d.action]
    why = explain(store, d, detail) if verdict != "approved" else ""
    # v4 "restate" verdict (Ctrl-Z for an uncertain step): the first time Jev is unsure about an agent's intent,
    # the agent restates it precisely; only an intent that is still unclear goes to the user.
    mine = [it for it in sess["intents"] if it.get("agent") == agent]
    if verdict == "ask_human" and not (mine and mine[-1]["verdict"] == "restate"):
        verdict = "restate"
    unhandled = failed is not None and detail.get("handles_failure", 1.0) < 0.5
    if unhandled and verdict == "approved":
        verdict = "approved_with_note"
        why = (f"- your last command failed (`{failed['command']}` -> {failed['last_line']}), and this intent "
               "doesn't say how you'll deal with that")
    row = store.add_intent({**base, "verdict": verdict, "why": why})
    s = store.session()
    if failed is not None and not unhandled:  # the failed step has been dealt with
        s["failed_step"] = None
    if verdict != "rejected":  # v4 loop L3 -> L1: a fresh intent covers files a drifted subagent touched
        for f in files:
            s["fresh_intent_needed"].pop(f, None)
    store.save_session(s)
    store.log({"stage": "intent", "agent": agent, "target": target,
               "reason": intent[:300], **d.as_dict(), **({"action": "restate"} if verdict == "restate" else {}),
               "verdict": verdict,
               "pattern": detail["pattern"] if d.risks.get("rationalizing", 0) >= 0.5 else None,
               "violations": {k: round(v, 3) for k, v in detail["violations"].items()},
               "conflicts": detail["conflicts"], "escalated": detail.get("escalated"),
               "handles_failure": detail.get("handles_failure"), "suspect": suspect or None,
               "tokens": detail["tokens"], "ms": int((time.time() - t0) * 1000)})
    if suspect:
        why = (why + "\n" if why else "") + "".join(
            f"- {f} was named in a contradicted claim (\"{sess['suspect_files'][f][:100]}\"), so it got a deep look\n"
            for f in suspect)
    if verdict == "approved":
        return f"{row['id']} approved. Go ahead: {target or 'no files listed'}." + (f"\n{why}" if suspect else "")
    if verdict == "approved_with_note":
        if unhandled:
            return f"{row['id']} approved, but deal with the failed step first:\n{why}"
        return f"{row['id']} approved, but stay on the goal: {store.session().get('goal')}\n{why}"
    if verdict == "ask_human":
        return f"{row['id']} needs the user's confirmation before you proceed:\n{why}\nAsk the user."
    if verdict == "restate":
        return (f"{row['id']}: Hall Monitor isn't sure about this intent:\n{why}\n"
                "Call declare_intent again, saying exactly which change you'll make, in which files, and how it "
                "serves the goal. If it's still unclear, the user will be asked.")
    return (f"{row['id']} REJECTED. Do not do this:\n{why}\n"
            "Choose an approach that respects the active decisions, or ask the user to change them.")


def pre_tool(p, store):
    cfg, sess = store.config(), store.session()
    tool = P.tool(p)
    path, command, detail_text = P.describe(tool, P.tool_input(p))
    command = evidence.repo_command(store.root, command)
    rel = rel_path(store.root, path, base=P.first(p, "cwd")) if path else None

    if tool in P.SPAWN_TOOLS:
        return spawn_check(p, store)
    if rel and tool in P.EDIT_TOOLS and is_protected(store.root, rel):  # rel is already resolved against cwd
        store.log({"stage": "step", "tool": tool, "target": rel, "action": "block",
                   "note": "protected: Hall Monitor's own configuration and records"})
        return 2, "", ("Hall Monitor: .bob/ and .hallmonitor/ hold Hall Monitor's own configuration and records, "
                       "so they can't be edited during a supervised task. Ask the user if a change there is needed.")
    if rel and tool in P.EDIT_TOOLS and rel.lower() == cfg["claims_file"].lower():
        from . import receipts
        return receipts.check_hook(store, detail_text)
    if rel and tool in P.EDIT_TOOLS and any(fnmatch.fnmatch(rel, g) for g in cfg["plan_globs"]):
        from . import plan
        return plan.check(store, detail_text)
    if command and re.match(cfg["safe_commands"], command):
        store.log({"stage": "step", "tool": tool, "target": command, "action": "allow", "note": "safe command"})
        return 0, "", ""

    intent = store.intent_for(path=rel, command=command)
    reason = intent["intent"] if intent else P.assistant_text(p)
    if intent is None and cfg["require_intent"] and not reason:
        store.log({"stage": "step", "tool": tool, "target": rel or command, "action": "block",
                   "note": "no declared intent"})
        return 2, "", ("Hall Monitor: declare your intent first. Call the hall-monitor MCP tool "
                       f"declare_intent with the files/commands you will touch ({rel or command}).")
    if intent and intent["verdict"] == "rejected":
        store.log({"stage": "step", "tool": tool, "target": rel or command, "action": "block",
                   "note": f"intent {intent['id']} was rejected"})
        return 2, "", f"Hall Monitor: intent {intent['id']} was rejected, so this action is blocked:\n{intent['why']}"
    flagged_at = sess["fresh_intent_needed"].get(rel) if rel and tool in P.EDIT_TOOLS else None
    if flagged_at and (intent is None or intent["t"] < flagged_at):  # v4 loop L3 -> L1
        store.log({"stage": "step", "tool": tool, "target": rel, "action": "block",
                   "note": "a drifted subagent changed this file; a fresh intent is needed"})
        return 2, "", (f"Hall Monitor: a subagent whose result may have drifted changed {rel}. Check its change, "
                       f"then call declare_intent for {rel} before building on it.")

    t0 = time.time()
    # Real Bob, Sept 27: cut to 1,200 characters, an edit adding three methods showed Jev only the first one,
    # so it judged the edit a mismatch with its intent, and the block revoked the intent. Show the whole
    # edit up to MAX_EDIT_CHARS, and say so when some of it is left out.
    content = detail_text if len(detail_text) <= MAX_EDIT_CHARS else (
        detail_text[:MAX_EDIT_CHARS] + f"\n[... {len(detail_text) - MAX_EDIT_CHARS} more characters not shown]")
    action = {"tool": tool, "target": rel or command, "content": content}
    # A command that is exactly one the approved intent declared matches it by definition: code decides
    # that, and Jev only checks the action itself (destructive? breaks a rule? on-task?).
    exact = bool(intent and command and command.strip() in {c.strip() for c in intent.get("commands", [])})
    try:
        d, det = judge(store, action, reason=None if exact else reason, check_match=intent is not None and not exact,
                       agent=intent["agent"] if intent else "main",
                       agent_task=intent.get("agent_task") if intent else None,
                       deep=bool(rel and rel in sess["suspect_files"]))  # v4 loop L4 -> L1
        # Parallel agents can each have an approved intent for the same file, and the hook can't tell which agent
        # made the edit. Real Bob, Sept 27: subagent-A's limiter edit to app/service.py was checked against
        # subagent-B's newer docstring intent, blocked as a mismatch, and B's intent revoked. So an edit that
        # doesn't match the newest covering intent is checked against the other agents' before it's blocked.
        # An uncertain mismatch too, and the same agent's older intents: real Bob, Sept 27, a test edit at mismatch
        # 0.26 went to the user although an earlier intent of the same agent covered it.
        if intent and not exact and d.action != "allow" and d.risks.get("mismatch", 0) >= cfg["uncertain_band"][0]:
            for other in store.intents_covering(path=rel, command=command, exclude_id=intent["id"])[:3]:
                d2, det2 = judge(store, action, reason=other["intent"], check_match=True, agent=other["agent"],
                                 agent_task=other.get("agent_task"))
                if d2.risks.get("mismatch", 0) < min(0.5, d.risks.get("mismatch", 0)):
                    intent, reason, d, det = other, other["intent"], d2, det2
                    break
    except jev.JevRefused:
        # Decided by code alone. Only a command that is exactly one an approved intent declared goes ahead:
        # that exact command was already judged (destructive? breaks a rule?) when the intent was approved.
        # An edit's content was never judged, so it waits for the user.
        judged = exact and intent["verdict"] in ("approved", "approved_with_note")
        store.log({"stage": "step", "tool": tool, "target": rel or command, "action": "allow" if judged else "block",
                   "fallback": "jev_refused", "note": "Jev couldn't check this; decided by code"})
        return (0, "", "") if judged else (2, "", "Hall Monitor couldn't check this action; ask the user.")
    sess = store.session()
    sess["actions"].append({"tool": tool, "target": rel or command, "decision": d.action})
    store.save_session(sess)
    store.log({"stage": "step", "tool": tool, "target": rel or command, "intent": intent["id"] if intent else None,
               "reason": (reason or "")[:300], **d.as_dict(),
               "pattern": det["pattern"] if d.risks.get("rationalizing", 0) >= 0.5 else None,
               "violations": {k: round(v, 3) for k, v in det["violations"].items()},
               "escalated": det.get("escalated"), "tokens": det["tokens"], "ms": int((time.time() - t0) * 1000)})
    if d.action == "allow":
        return 0, "", ""
    if d.action == "rebrief":
        store.queue_note("You drifted from the goal. Refocus on: " + (sess.get("goal") or "the user's request"))
        return 0, "", ""
    why = explain(store, d, det)
    if intent and d.risks.get("mismatch", 0) >= 0.5:
        store.revoke_intent(intent["id"], "the edit did something other than what was declared")
    if d.action == "ask_human":
        return 2, "", "Hall Monitor is unsure whether this action is safe:\n" + why + "\nAsk the user to confirm."
    return 2, "", ("Hall Monitor blocked this action:\n" + why +
                   "\nChoose an approach that respects the active decisions, or ask the user to change them.")


def spawn_check(p, store):
    """PreToolUse on spawn_subagent: the subagent's brief is checked against the goal, the decisions and
    the other agents' work BEFORE it starts. This works whether or not hooks fire inside subagents."""
    t0 = time.time()
    inp = P.tool_input(p)
    brief_text, kind = P.subagent_brief(inp)
    n = sum(1 for it in store.session()["intents"] if it.get("source") == "spawn") + 1
    # Bob's `name` is the preset, shared by parallel subagents, so number them to keep their work apart
    name = P.first(inp, "title", default=None) or f"{kind}-subagent-{n}"
    action = {"tool": "spawn_subagent", "subagent_type": kind, "brief": brief_text[:1500]}
    try:
        d, det = judge(store, action, reason=brief_text, agent=name, agent_task=brief_text)
    except jev.JevRefused:
        store.log({"stage": "spawn", "agent": name, "target": f"{kind}: {brief_text[:120]}", "action": "block",
                   "fallback": "jev_refused"})
        return 2, "", f"Hall Monitor couldn't check the brief for {name}; ask the user."
    verdict = VERDICT[d.action]
    why = explain(store, d, det) if verdict != "approved" else ""
    store.add_intent({"agent": name, "agent_task": brief_text[:600], "intent": brief_text[:600], "files": [],
                      "commands": [], "verdict": verdict, "why": why, "source": "spawn", "subagent_type": kind})
    store.log({"stage": "spawn", "agent": name, "target": f"{kind}: {brief_text[:120]}", **d.as_dict(),
               "verdict": verdict, "pattern": det["pattern"] if d.risks.get("rationalizing", 0) >= 0.5 else None,
               "violations": {k: round(v, 3) for k, v in det["violations"].items()}, "conflicts": det["conflicts"],
               "escalated": det.get("escalated"), "tokens": det["tokens"], "ms": int((time.time() - t0) * 1000)})
    if d.action in ("block", "ask_human"):
        return 2, "", f"Hall Monitor blocked spawning {name}:\n{why}"
    return 0, "", ""


def subagent_return(p, store):
    """PostToolUse on spawn_subagent: check the returned summary before the parent builds on it
    (inherited goal drift). PostToolUse can't block, so a drifted result becomes a flag that the next
    declare_intent result and the next prompt's context both carry."""
    t0 = time.time()
    brief_text, kind = P.subagent_brief(P.tool_input(p))
    summary = P.tool_output(p)
    if not summary.strip():
        return 0, "", ""
    try:
        answers, usage = jev.ask({"goal": store.session().get("goal"), "assigned_task": brief_text[:1500],
                                  "subagent_summary": summary[:3000]},
                                 {"serves": Q.SUBAGENT_SERVES, "drifted": Q.SUBAGENT_DRIFTED})
    except jev.JevRefused:
        store.add_flag(f"Hall Monitor couldn't check what the {kind} subagent returned; review it before building on it.")
        return 0, "", ""
    off = jev.p_levels(answers["serves"], [0, 1])
    drift = answers["drifted"]["noul"]
    flagged = off >= 0.5 or drift >= 0.6
    store.log({"stage": "subagent_return", "agent": kind, "target": brief_text[:120],
               "action": "flag" if flagged else "accept", "risks": {"off_goal": off, "drifted": drift},
               "tokens": jev.tokens(usage), "ms": int((time.time() - t0) * 1000)})
    if flagged:  # delivered once, at the top of the next MCP result or the next briefing
        # v4 loop L3 -> L1: files edited since the subagent was spawned need a fresh intent before the
        # parent edits them again.
        spawned = max((e["t"] for e in store.events() if e.get("stage") == "spawn"), default=0)
        touched = {r["file"] for r in store.evidence() if r.get("kind") == "edit" and r.get("t", 0) >= spawned}
        if touched:
            s = store.session()
            s["fresh_intent_needed"].update({f: time.time() for f in touched})
            store.save_session(s)
        store.add_flag(f"A {kind} subagent's result may have drifted from its task \"{brief_text[:100]}\" "
                       f"(drifted p={drift:.2f}, off-goal p={off:.2f}). Check its changes before building on them.")
    return 0, "", ""


def post_tool(p, store):
    """PostToolUse can't block or talk back. Spawns get the return check; edits and commands become
    receipts in the evidence ledger (which also drives checkpoints and the stall counter)."""
    if P.tool(p) in P.SPAWN_TOOLS:
        return subagent_return(p, store)
    evidence.record(p, store)
    return 0, "", ""
