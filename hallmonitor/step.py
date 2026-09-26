"""DURING: judge declared intents (MCP declare_intent) and every tool call before it runs (PreToolUse).

Bob's hook payload carries only {tool, input}, never the agent's reasoning. So the Supervised mode
makes Bob declare its intent through the Hall Monitor MCP tool first. That call is judged
immediately and the verdict goes straight back to Bob as the tool result (hooks can't talk back).
PreToolUse then enforces it: no covering intent means no edit, a rejected intent stays rejected,
and an edit that does something other than what was declared is blocked.
"""
import fnmatch
import re
import time
from pathlib import Path

from . import evidence, jev, payload as P, policy, questions as Q
from .store import is_protected


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
    questions = Q.step(ids, bool(reason), check_match, len(others))
    if failed_step and reason:
        state["last_failed_step"] = failed_step
        questions["handles_failure"] = Q.HANDLES_FAILURE
    answers, usage = jev.ask(state, questions)
    viol = {d: answers[f"violates_{d}"]["noul"] for d in ids}
    risks = {
        "destructive": answers["destructive"]["noul"],
        # max, not noisy-or: many weak, correlated guesses must not add up to a confident violation
        "violates": max(viol.values(), default=0.0),
        "off_task": jev.p_levels(answers["on_task"], [0, 1]),
    }
    pattern = None
    if "rationalization" in answers:
        dist = answers["rationalization"]["probabilities"]
        risks["rationalizing"] = 1 - dist.get("none", 0.0)
        pattern = max((k for k in dist if k != "none"), key=dist.get)
    if "matches_intent" in answers:
        risks["mismatch"] = 1 - answers["matches_intent"]["noul"]
    conflicts = {others[j]["agent"]: answers[f"conflict_{j}"]["noul"] for j in range(len(others))}
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
    files = [str(f).replace("\\", "/") for f in files or []]
    commands = list(commands or [])
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

    failed = sess["failed_step"]
    try:
        d, detail = judge(store, {"declared_intent": intent, "files": files, "commands": commands},
                          reason=intent, agent=agent, agent_task=agent_task, failed_step=failed)
    except jev.JevRefused:
        row = store.add_intent({**base, "verdict": "ask_human", "why": "- Hall Monitor couldn't check this intent."})
        store.log({"stage": "intent", "agent": agent, "target": target, "reason": intent[:300],
                   "action": "ask_human", "verdict": "ask_human", "fallback": "jev_refused"})
        return f"{row['id']}: Hall Monitor couldn't check this; ask the user."
    verdict = VERDICT[d.action]
    why = explain(store, d, detail) if verdict != "approved" else ""
    unhandled = failed is not None and detail.get("handles_failure", 1.0) < 0.5
    if unhandled and verdict == "approved":
        verdict = "approved_with_note"
        why = (f"- your last command failed (`{failed['command']}` -> {failed['last_line']}), and this intent "
               "doesn't say how you'll deal with that")
    row = store.add_intent({**base, "verdict": verdict, "why": why})
    if failed is not None and not unhandled:  # the failed step has been dealt with
        s = store.session()
        s["failed_step"] = None
        store.save_session(s)
    store.log({"stage": "intent", "agent": agent, "target": target,
               "reason": intent[:300], **d.as_dict(), "verdict": verdict,
               "pattern": detail["pattern"] if d.risks.get("rationalizing", 0) >= 0.5 else None,
               "violations": {k: round(v, 3) for k, v in detail["violations"].items()},
               "conflicts": detail["conflicts"], "escalated": detail.get("escalated"),
               "handles_failure": detail.get("handles_failure"),
               "tokens": detail["tokens"], "ms": int((time.time() - t0) * 1000)})
    if verdict == "approved":
        return f"{row['id']} approved. Go ahead: {target or 'no files listed'}."
    if verdict == "approved_with_note":
        if unhandled:
            return f"{row['id']} approved, but deal with the failed step first:\n{why}"
        return f"{row['id']} approved, but stay on the goal: {store.session().get('goal')}\n{why}"
    if verdict == "ask_human":
        return f"{row['id']} needs the user's confirmation before you proceed:\n{why}\nAsk the user."
    return (f"{row['id']} REJECTED. Do not do this:\n{why}\n"
            "Choose an approach that respects the active decisions, or ask the user to change them.")


def pre_tool(p, store):
    cfg, sess = store.config(), store.session()
    tool = P.tool(p)
    path, command, detail_text = P.describe(tool, P.tool_input(p))
    rel = str(path).replace("\\", "/") if path else None

    if tool in P.SPAWN_TOOLS:
        return spawn_check(p, store)
    if rel and tool in P.EDIT_TOOLS and is_protected(store.root, rel, base=P.first(p, "cwd")):
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

    t0 = time.time()
    action = {"tool": tool, "target": rel or command, "content": detail_text[:1200]}
    # A command that is exactly one the approved intent declared matches it by definition: code decides
    # that, and Jev only checks the action itself (destructive? breaks a rule? on-task?).
    exact = bool(intent and command and command.strip() in {c.strip() for c in intent.get("commands", [])})
    try:
        d, det = judge(store, action, reason=None if exact else reason, check_match=intent is not None and not exact,
                       agent=intent["agent"] if intent else "main",
                       agent_task=intent.get("agent_task") if intent else None)
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
    name = P.first(inp, "name", "title", default=None) or f"{kind}-subagent-{n}"
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
