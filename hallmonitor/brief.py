"""BEFORE: context briefing. SessionStart and UserPromptSubmit stdout becomes Bob's context."""
import re
import time
from pathlib import Path

from . import gitutil, jev, ledger, lessons, payload as P, questions as Q


# Lines of a pasted traceback, log, shell session or code block: not something the user says.
LOG_LINE_RE = re.compile(r"^(\s{2,}\S|\t|Traceback \(|File \"|\s*at \S+\(|[A-Z]\w*(Error|Exception|Warning):|>>> |\$ |"
                         r"PS [A-Z]:\\|[A-Z]:\\\S+>|```|E\s{2,}|FAILED |PASSED |=+ |-{3,})")
SHORT_RULE_RE = re.compile(r"\b(no|not|only|never|don['’]t)\b", re.I)


def prose(text):
    return "\n".join(l for l in (text or "").splitlines() if not LOG_LINE_RE.match(l)).strip() or (text or "")


def sentences(text, limit=12, short_rules=False):
    """The prose sentences of a prompt. Real risk, Sept 28: a rule after a pasted 13-line traceback was never judged
    (the log filled all 12 slots), and two-word rules like "No Redis." were dropped as too short (`short_rules`)."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", prose(text))
    out = [re.sub(r"^\s*([-*]|\d+[.)])\s*", "", s).strip() for s in parts]
    return [s for s in out if len(s.split()) >= 3
            or (short_rules and len(s.split()) == 2 and SHORT_RULE_RE.search(s))][:limit]


def _brief(store, extra=None, optional=None):
    """The briefing. `optional` lines (the last session's lessons) go after the decisions, and only as
    many as fit within max_brief_chars, so they never push out the findings or the protocol."""
    cfg, sess = store.config(), store.session()
    lines = ["[Hall Monitor]"]
    if sess.get("goal"):
        lines.append(f"Goal: {sess['goal'][:300]}")
    decisions = store.active_decisions()
    if decisions:
        lines.append("Active decisions (do not break these without asking the user):")
        lines += [f"- {d['id']}: {d['text']}" + (" (checked when you finish)" if d.get("kind") == "obligation" else "")
                  for d in decisions]
    lines += extra or []
    at = len(lines)
    notes = store.pop_pending()
    if notes:
        lines.append("Hall Monitor findings to address first:")
        lines += [f"- {n}" for n in notes]
    lines.append("Protocol: call hall-monitor declare_intent before any edit or command; if a tool is reported "
                 "as blocked, call explain_block to learn why; when done, call list_evidence, then "
                 "submit_claims with each claim citing the receipt IDs (E1, E2, ...) that prove it. Claims are "
                 "checked against those receipts, the diff, a fresh test run and sabotage probes.")
    room, fit = cfg["max_brief_chars"] - len("\n".join(lines)), []
    for line in optional or []:
        if len(line) + 1 > room:
            break
        fit.append(line)
        room -= len(line) + 1
    if len(fit) > 1:  # a heading with at least one line under it
        lines[at:at] = fit
    return "\n".join(lines)[:cfg["max_brief_chars"]]


def session_start(p, store):
    seeds, tok = store.agents_md_decisions(), 0
    if seeds:
        scoped, usage = ledger.scope(store, seeds)
        tok = jev.tokens(usage)
        for text, (kind, one_step) in zip(seeds, scoped):
            store.add_decision(text, "AGENTS.md", kind=kind, per_action=one_step)
    sess = store.session()
    # A new session: rules the user stated in an earlier one no longer apply (store.active_decisions)
    sess.update(base=gitutil.head(store.root), actions=[], commands=[], off_task_streak=0,
                session_id=f"S{int(time.time() * 1000)}", user_rule_sentences=[], unjudged_sentences=[])
    store.save_session(sess)
    learned = lessons.brief_lines(store)  # v4.2: the last session's lessons, read before this one is logged
    store.log({"stage": "session_start", "action": "brief", "decisions": len(store.active_decisions()),
               "tokens": tok, "lessons": len(learned[1:]) or None})
    return 0, _brief(store, optional=learned), ""


def _start_here(store, goal, max_files=40):
    files = [f for f in gitutil.tracked_files(store.root) if not f.startswith(".")][:max_files]
    if not files:
        return [], 0
    heads = []
    for f in files:
        try:
            first = (Path(store.root) / f).read_text(encoding="utf-8").splitlines()[:3]
        except (OSError, UnicodeDecodeError):
            first = []
        heads.append({"path": f, "starts_with": " | ".join(first)[:160]})
    answers, usage = jev.ask({"goal": goal, "files": heads}, {f"file_{i}": Q.file_relevance(i) for i in range(len(files))})
    scored = sorted(((answers[f"file_{i}"]["score"], f) for i, f in enumerate(files)), reverse=True)
    return [f for s, f in scored if s >= 1.8][:5], jev.tokens(usage)


def user_prompt(p, store):
    t0 = time.time()
    text = P.prompt(p)
    sess = store.session()
    sents = sentences(text, short_rules=True)
    # Kept before Jev is asked: if Jev refuses, the hook tells Bob to record the user's rules with record_decision,
    # and those must still count as the user's (ledger.said_by_user).
    sess["unjudged_sentences"] = sents
    store.save_session(sess)
    active = store.active_decisions()
    # Speculative fan-out: whether it's a new task, which sentences are decisions, and (for every
    # sentence x active decision) whether it contradicts that decision. Code uses what applies.
    qs = {"new_task": Q.NEW_TASK}
    for i in range(len(sents)):
        qs[f"decision_{i}"] = Q.is_decision(i)
        qs[f"scope_{i}"] = Q.decision_scope(f"stated in `sentences[{i}]`")
        qs[f"one_step_{i}"] = Q.breaks_in_one_step(f"stated in `sentences[{i}]`")
        for d in active:
            qs[f"contra_{i}_{d['id']}"] = Q.sentence_contradicts(i, d["id"])
    state = {"prompt": text[:2000], "current_goal": sess.get("goal"), "sentences": sents,
             "decisions": {d["id"]: d["text"] for d in active}}
    answers, usage = jev.ask(state, qs)
    tok = jev.tokens(usage)

    new_task = sess.get("goal") is None or answers["new_task"]["noul"] >= 0.5
    if new_task:
        sess["goal"] = prose(text)[:600]
        # A new task starts its own Receipts rounds. Real Bob, Sept 27: a task began one send-back from STUCK
        # because the count from the task before it (a /decisions turn) carried over.
        sess.update({"send_backs": 0, "last_send_back": None, "uncited_retry_used": False, "pending_audits": {},
                     "agent_pending_audits": {}, "audit_briefs": {}, "suspect_files": {}, "fresh_intent_needed": {}})
    sess["stalls"] = 0  # the user has stepped in: the stall counter starts again
    # What the user said as rules (ledger.said_by_user): a looser bar than recording, since Bob may re-record one
    sess["user_rule_sentences"] = (sess.get("user_rule_sentences", []) +
                                   [s for i, s in enumerate(sents) if answers[f"decision_{i}"]["noul"] >= 0.5])[-30:]
    sess["unjudged_sentences"] = []
    added = []
    for i, s in enumerate(sents):
        if answers[f"decision_{i}"]["noul"] < 0.6:
            continue
        hits = [d["id"] for d in active if answers[f"contra_{i}_{d['id']}"]["noul"] >= 0.7]
        row = store.add_decision(s, "user", kind=answers[f"scope_{i}"]["choice"],
                                 supersedes=hits[0] if hits else None,
                                 per_action=answers[f"one_step_{i}"]["noul"] >= 0.5, session=sess.get("session_id"))
        added.append(row)
    store.save_session(sess)

    extra = []
    if added:
        extra.append("New decisions recorded: " + "; ".join(
            f"{r['id']}" + (f" (replaces {r['supersedes']})" if r["supersedes"] else "") for r in added))
    if new_task:
        files, t = _start_here(store, sess["goal"])
        tok += t
        if files:
            extra.append("Start with: " + ", ".join(files))
    store.log({"stage": "brief", "action": "new_task" if new_task else "follow_up",
               "decisions_added": [r["text"] for r in added], "tokens": tok,
               "ms": int((time.time() - t0) * 1000)})
    return 0, _brief(store, extra), ""
