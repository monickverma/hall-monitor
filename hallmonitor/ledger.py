"""The decision ledger's write path (MCP record_decision).

Bob reads policy documents natively (.pdf/.docx/.md; the extract-decisions skill) and records each
decision with its source and a verbatim quote. Every write is checked against the active decisions:
a contradiction supersedes the old decision only if the new source has at least its authority.
The agent can propose decisions but can never override the user's or a policy document's.
"""
import re
import time
from pathlib import Path

from . import gitutil, jev, questions as Q
from .store import per_action

AUTHORITY = {"user": 3, "document": 2, "agent": 1}
USER_RE = re.compile(r"^(the\s+)?(user|prompt|chat|developer)\b", re.I)
AGENT_RE = re.compile(r"^(agent|bob|ibm bob|main|assistant|ai|claude)\b|subagent", re.I)


def source_path(source):
    """The file part of a source such as "docs/security-policy.pdf §2" or "AGENTS.md (Decisions)"."""
    return re.split(r"\s*(?:§|\(|,|\s-\s|\s+p\.|\s+page\s|\s+section\s)", (source or "").strip(), maxsplit=1)[0].strip()


def trusted_document(store, source):
    """A document source counts only if it is a file the repo tracks and the agent hasn't edited this session: a
    path Bob made up, or a file it wrote itself, must not outrank a policy document. Real risk, Sept 28: any unknown
    source got a document's authority, and a tie supersedes."""
    path = source_path(source).replace("\\", "/").lstrip("./")
    if not path or not (Path(store.root) / path).is_file():
        return False
    if path.lower() not in {f.lower() for f in gitutil.tracked_files(store.root)}:
        return False
    edited = {str(r.get("file") or "").lower() for r in store.evidence() if r.get("kind") == "edit"}
    return path.lower() not in edited


def authority(source, store=None):
    """Authority of a rule's source. With `store`, a claimed document is checked (trusted_document); without it
    (a row already in the ledger, vetted when it was recorded) the source is taken as written."""
    s = (source or "").strip()
    if USER_RE.match(s):
        return AUTHORITY["user"]
    if not s or AGENT_RE.search(s):
        return AUTHORITY["agent"]
    if store is not None and not trusted_document(store, s):
        return AUTHORITY["agent"]
    return AUTHORITY["document"]  # a file path: AGENTS.md, docs/security-policy.pdf, an ADR ...


NEG_RE = re.compile(r"\b(?:not|no|never|without|cannot|nor|avoid\w*|forbid\w*|prohibit\w*)\b|n['’]t\b", re.I)


def _words(text):
    return {w for w in re.findall(r"[a-z0-9_=!<>]+", (text or "").lower()) if len(w) >= 3 or not w.isalpha()}


def said_by_user(store, text, min_overlap=0.7):
    """True when the user said `text` as a rule this session: most of its words are in one sentence of a user prompt
    that the briefing took for a rule (or couldn't judge), with the same polarity. Real risk, Sept 28: shared words
    alone let "Password comparison may use ==" pass as the user's "do not use == for passwords"."""
    words, neg = _words(text), len(NEG_RE.findall(text or "")) % 2
    sess = store.session()
    return bool(words) and any(len(words & _words(c)) >= min_overlap * len(words)
                               and len(NEG_RE.findall(c)) % 2 == neg
                               for c in sess.get("user_rule_sentences", []) + sess.get("unjudged_sentences", []))


def scope(store, texts):
    """Jev's kind (limit/obligation) and whether one edit can break it, for each rule text, in one request."""
    qs = {}
    for i in range(len(texts)):
        qs[f"scope_{i}"] = Q.decision_scope(f"`decisions[{i}]`")
        qs[f"one_step_{i}"] = Q.breaks_in_one_step(f"`decisions[{i}]`")
    answers, usage = jev.ask({"decisions": list(texts)}, qs)
    return [(answers[f"scope_{i}"]["choice"], answers[f"one_step_{i}"]["noul"] >= 0.5) for i in range(len(texts))], usage


def record_decision(store, text, source, quote=None):
    t0 = time.time()
    note = ""
    # Bob chooses `source`. A user's rule outranks the policy document, so an agent (or text planted in a file it
    # read) could overrule D2 by claiming the user said so. The user's own prompts are recorded by the
    # UserPromptSubmit hook; here 'user' counts only if the user said this rule, and a document only if it's real.
    level = authority(source, store)
    if level == AUTHORITY["user"] and not said_by_user(store, text):
        source, level, note = "agent", AUTHORITY["agent"], " (recorded as the agent's: the user didn't say this)"
    elif level == AUTHORITY["agent"] and not AGENT_RE.search(source or "") and not USER_RE.match(source or ""):
        note = f" (recorded as the agent's: {source_path(source) or 'the source'} isn't a document the repo tracks)"
        source = f"agent (cited {source})"
    active = store.active_decisions()
    qs = {"scope": Q.decision_scope("`decision`"), "one_step": Q.breaks_in_one_step("`decision`")}
    qs.update({f"contra_{d['id']}": Q.sentence_contradicts(0, d["id"]) for d in active})
    answers, usage = jev.ask({"decision": text, "sentences": [text],
                              "decisions": {d["id"]: d["text"] for d in active}}, qs)
    kind = answers["scope"]["choice"]
    hits = sorted(((answers[f"contra_{d['id']}"]["noul"], d) for d in active), key=lambda x: -x[0])
    hits = [(p, d) for p, d in hits if p >= 0.7]
    if hits and level < authority(hits[0][1]["source"]):
        store.log({"stage": "ledger", "action": "reject", "text": text, "source": source,
                   "conflicts_with": hits[0][1]["id"], "tokens": jev.tokens(usage)})
        d = hits[0][1]
        return (f"REJECTED{note}: contradicts {d['id']} \"{d['text']}\" (source: {d['source']}), which has higher "
                "authority. Ask the user if it should change.")
    row = store.add_decision(text, source, kind=kind, supersedes=hits[0][1]["id"] if hits else None,
                             per_action=answers["one_step"]["noul"] >= 0.5,
                             session=store.session().get("session_id") if level == AUTHORITY["user"] else None)
    if quote:
        row["quote"] = quote
    store.log({"stage": "ledger", "action": "record", "id": row["id"], "text": text, "source": source,
               "kind": kind, "per_action": row.get("per_action"), "quote": quote, "supersedes": row["supersedes"],
               "tokens": jev.tokens(usage), "ms": int((time.time() - t0) * 1000)})
    how = ("checked on every action" if kind == "limit" else
           "checked on every action and on the finished work (Receipts)" if per_action(row) else
           "checked on the finished work (Receipts)")
    sup = f", supersedes {row['supersedes']}" if row["supersedes"] else ""
    return f"Recorded {row['id']} ({kind}, {how}{sup}){note}: {text}"


def list_decisions(store):
    rows = store.active_decisions()
    if not rows:
        return "No active decisions."
    return "\n".join(f"{d['id']} [{d.get('kind', 'limit')}, from {d['source']}]: {d['text']}" for d in rows)
