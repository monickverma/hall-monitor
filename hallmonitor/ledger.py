"""The decision ledger's write path (MCP record_decision).

Bob reads policy documents natively (.pdf/.docx/.md; the extract-decisions skill) and records each
decision with its source and a verbatim quote. Every write is checked against the active decisions:
a contradiction supersedes the old decision only if the new source has at least its authority.
The agent can propose decisions but can never override the user's or a policy document's.
"""
import time

from . import jev, questions as Q

AUTHORITY = {"user": 3, "document": 2, "agent": 1}


def authority(source):
    s = (source or "").lower()
    if s in ("user", "prompt"):
        return AUTHORITY["user"]
    if s in ("agent", "bob") or s.startswith("agent"):
        return AUTHORITY["agent"]
    return AUTHORITY["document"]  # a file path: AGENTS.md, docs/security-policy.pdf, an ADR ...


def record_decision(store, text, source, quote=None):
    t0 = time.time()
    active = store.active_decisions()
    qs = {"scope": Q.decision_scope("`decision`")}
    qs.update({f"contra_{d['id']}": Q.sentence_contradicts(0, d["id"]) for d in active})
    answers, usage = jev.ask({"decision": text, "sentences": [text],
                              "decisions": {d["id"]: d["text"] for d in active}}, qs)
    kind = answers["scope"]["choice"]
    hits = sorted(((answers[f"contra_{d['id']}"]["noul"], d) for d in active), key=lambda x: -x[0])
    hits = [(p, d) for p, d in hits if p >= 0.7]
    duplicate = None
    if hits and authority(source) < authority(hits[0][1]["source"]):
        store.log({"stage": "ledger", "action": "reject", "text": text, "source": source,
                   "conflicts_with": hits[0][1]["id"], "tokens": jev.tokens(usage)})
        d = hits[0][1]
        return (f"REJECTED: contradicts {d['id']} \"{d['text']}\" (source: {d['source']}), which has higher "
                "authority. Ask the user if it should change.")
    row = store.add_decision(text, source, kind=kind, supersedes=hits[0][1]["id"] if hits else None)
    if quote:
        row["quote"] = quote
    store.log({"stage": "ledger", "action": "record", "id": row["id"], "text": text, "source": source,
               "kind": kind, "quote": quote, "supersedes": row["supersedes"], "tokens": jev.tokens(usage),
               "ms": int((time.time() - t0) * 1000)})
    how = "checked on every action" if kind == "limit" else "checked on the finished work (Receipts)"
    sup = f", supersedes {row['supersedes']}" if row["supersedes"] else ""
    return f"Recorded {row['id']} ({kind}, {how}{sup}): {text}"


def list_decisions(store):
    rows = store.active_decisions()
    if not rows:
        return "No active decisions."
    return "\n".join(f"{d['id']} [{d.get('kind', 'limit')}, from {d['source']}]: {d['text']}" for d in rows)
