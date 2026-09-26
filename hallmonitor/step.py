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

from . import jev, payload as P, policy, questions as Q


def _read(root, path, limit=3000):
    try:
        return (Path(root) / path).read_text(encoding="utf-8")[:limit]
    except (OSError, UnicodeDecodeError, TypeError):
        return None


def judge(store, action, reason=None, check_match=False, agent="main", agent_task=None, deep=False):
    """One parallel Jev request over everything that matters for this action, then minimum expected loss."""
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
    answers, usage = jev.ask(state, Q.step(ids, bool(reason), check_match, len(others)))
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
    if d.escalate and not deep:  # a closer look with full context is worth its cost
        d2, detail2 = judge(store, action, reason, check_match, agent, agent_task, deep=True)
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
    """MCP tool: judge a plan of action before any tool runs; the answer goes straight back to Bob."""
    t0 = time.time()
    files = [str(f).replace("\\", "/") for f in files or []]
    action = {"declared_intent": intent, "files": files, "commands": list(commands or [])}
    d, detail = judge(store, action, reason=intent, agent=agent, agent_task=agent_task)
    verdict = VERDICT[d.action]
    why = explain(store, d, detail) if verdict != "approved" else ""
    row = store.add_intent({"agent": agent, "agent_task": agent_task, "intent": intent, "files": files,
                            "commands": list(commands or []), "verdict": verdict, "why": why})
    flags = store.pop_flags()  # e.g. a subagent whose returned work drifted: say so before Bob builds on it
    prefix = ("Hall Monitor notes before you continue:\n" + "\n".join(f"- {f}" for f in flags) + "\n\n") if flags else ""
    store.log({"stage": "intent", "agent": agent, "target": ", ".join(files + list(commands or [])),
               "reason": intent[:300], **d.as_dict(), "verdict": verdict,
               "pattern": detail["pattern"] if d.risks.get("rationalizing", 0) >= 0.5 else None,
               "violations": {k: round(v, 3) for k, v in detail["violations"].items()},
               "conflicts": detail["conflicts"], "escalated": detail.get("escalated"),
               "tokens": detail["tokens"], "ms": int((time.time() - t0) * 1000)})
    if verdict == "approved":
        return prefix + f"{row['id']} approved. Go ahead: {', '.join(files + list(commands or [])) or 'no files listed'}."
    if verdict == "approved_with_note":
        return prefix + f"{row['id']} approved, but stay on the goal: {store.session().get('goal')}\n{why}"
    if verdict == "ask_human":
        return prefix + f"{row['id']} needs the user's confirmation before you proceed:\n{why}\nAsk the user."
    return prefix + (f"{row['id']} REJECTED. Do not do this:\n{why}\n"
                     "Choose an approach that respects the active decisions, or ask the user to change them.")


def pre_tool(p, store):
    cfg, sess = store.config(), store.session()
    tool = P.tool(p)
    path, command, detail_text = P.describe(tool, P.tool_input(p))
    rel = str(path).replace("\\", "/") if path else None

    if tool in P.SPAWN_TOOLS:
        return spawn_check(p, store)
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
    d, det = judge(store, action, reason=reason, check_match=intent is not None,
                   agent=intent["agent"] if intent else "main", agent_task=intent.get("agent_task") if intent else None)
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
    d, det = judge(store, action, reason=brief_text, agent=name, agent_task=brief_text)
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
    answers, usage = jev.ask({"goal": store.session().get("goal"), "assigned_task": brief_text[:1500],
                              "subagent_summary": summary[:3000]},
                             {"serves": Q.SUBAGENT_SERVES, "drifted": Q.SUBAGENT_DRIFTED})
    off = jev.p_levels(answers["serves"], [0, 1])
    drift = answers["drifted"]["noul"]
    flagged = off >= 0.5 or drift >= 0.6
    store.log({"stage": "subagent_return", "agent": kind, "target": brief_text[:120],
               "action": "flag" if flagged else "accept", "risks": {"off_goal": off, "drifted": drift},
               "tokens": jev.tokens(usage), "ms": int((time.time() - t0) * 1000)})
    if flagged:
        msg = (f"A {kind} subagent's result may have drifted from its task \"{brief_text[:100]}\" "
               f"(drifted p={drift:.2f}, off-goal p={off:.2f}). Check its changes before building on them.")
        store.add_flag(msg)
        store.queue_note(msg)
    return 0, "", ""


def post_tool(p, store):
    if P.tool(p) in P.SPAWN_TOOLS:
        return subagent_return(p, store)
    sess = store.session()
    tool = P.tool(p)
    path, command, _ = P.describe(tool, P.tool_input(p))
    if command:
        sess["commands"].append({"command": command, "output": P.tool_output(p)[-800:]})
    store.save_session(sess)
    return 0, "", ""
