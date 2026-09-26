"""BEFORE: context briefing. SessionStart and UserPromptSubmit stdout becomes Bob's context."""
import re
import time
from pathlib import Path

from . import gitutil, jev, payload as P, questions as Q


def sentences(text, limit=12):
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    out = [re.sub(r"^\s*([-*]|\d+[.)])\s*", "", s).strip() for s in parts]
    return [s for s in out if len(s.split()) >= 3][:limit]


def _brief(store, extra=None):
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
    notes = store.pop_notes()
    if notes:
        lines.append("Hall Monitor findings to address first:")
        lines += [f"- {n}" for n in notes]
    lines.append("Protocol: call hall-monitor declare_intent before any edit or command; if a tool is reported "
                 "as blocked, call explain_block to learn why; when done, call "
                 f"submit_claims (or write {cfg['claims_file']}). Claims are checked against the diff, a fresh "
                 "test run and sabotage probes.")
    return "\n".join(lines)[:cfg["max_brief_chars"]]


def session_start(p, store):
    seeds, tok = store.agents_md_decisions(), 0
    if seeds:
        answers, usage = jev.ask({"decisions": seeds},
                                 {f"scope_{i}": Q.decision_scope(f"`decisions[{i}]`") for i in range(len(seeds))})
        tok = jev.tokens(usage)
        for i, text in enumerate(seeds):
            store.add_decision(text, "AGENTS.md", kind=answers[f"scope_{i}"]["choice"])
    sess = store.session()
    sess.update(base=gitutil.head(store.root), actions=[], commands=[], off_task_streak=0)
    store.save_session(sess)
    store.log({"stage": "session_start", "action": "brief", "decisions": len(store.active_decisions()),
               "tokens": tok})
    return 0, _brief(store), ""


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
    sents = sentences(text)
    active = store.active_decisions()
    # Speculative fan-out: whether it's a new task, which sentences are decisions, and (for every
    # sentence x active decision) whether it contradicts that decision. Code uses what applies.
    qs = {"new_task": Q.NEW_TASK}
    for i in range(len(sents)):
        qs[f"decision_{i}"] = Q.is_decision(i)
        qs[f"scope_{i}"] = Q.decision_scope(f"stated in `sentences[{i}]`")
        for d in active:
            qs[f"contra_{i}_{d['id']}"] = Q.sentence_contradicts(i, d["id"])
    state = {"prompt": text[:2000], "current_goal": sess.get("goal"), "sentences": sents,
             "decisions": {d["id"]: d["text"] for d in active}}
    answers, usage = jev.ask(state, qs)
    tok = jev.tokens(usage)

    new_task = sess.get("goal") is None or answers["new_task"]["noul"] >= 0.5
    if new_task:
        sess["goal"] = text[:600]
    added = []
    for i, s in enumerate(sents):
        if answers[f"decision_{i}"]["noul"] < 0.6:
            continue
        hits = [d["id"] for d in active if answers[f"contra_{i}_{d['id']}"]["noul"] >= 0.7]
        row = store.add_decision(s, "user", kind=answers[f"scope_{i}"]["choice"],
                                 supersedes=hits[0] if hits else None)
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
