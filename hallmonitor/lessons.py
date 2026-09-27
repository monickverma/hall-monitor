"""Cross-session lessons (v4.2, L5 -> L0), in code only: no Jev.

When a session ends (the Stop hook, and again at the next SessionStart in case no Stop ran), its events
are summarized in at most 3 lines and saved to .hallmonitor/lessons.json:
- excuses rejected: the rationalization pattern and what it was for;
- claims sent back: the reason codes;
- stall patterns, and edits blocked because they targeted Hall Monitor's own files.
The next SessionStart briefing starts with "From your last session: ..." (within max_brief_chars).
A repository with no earlier session gets no line.
"""
import json
from collections import Counter

from .store import now

MAX_LINE = 160


def session_events(store):
    """The events of the current (or, at SessionStart, the just-ended) session: everything logged
    after the last session_start event."""
    events = store.events()
    starts = [i for i, e in enumerate(events) if e.get("stage") == "session_start"]
    return events[starts[-1] + 1:] if starts else events


def _short(x, n=60):
    x = str(x or "").strip()
    return x if len(x) <= n else x[:n - 1] + "…"


def _unique(xs, n):
    return list(dict.fromkeys(x for x in xs if x))[:n]


def summarize(events):
    """At most 3 lines about what went wrong in these events (empty if nothing did)."""
    excuses, stalls, protected = [], [], []
    sent_back = Counter()
    for e in events:
        stage, action = e.get("stage"), e.get("action")
        stopped = action in ("block", "ask_human") or e.get("verdict") in ("rejected", "ask_human")
        if stage in ("intent", "step", "spawn") and e.get("pattern") and stopped:
            excuses.append(f"{e['pattern'].replace('_', ' ')} ({_short(e.get('target'))})")
        elif stage == "receipts" and action in ("send_back", "stuck", "needs_evidence"):
            codes = e.get("codes") or {}
            for claim, state in (e.get("verdicts") or {}).items():
                if state in ("contradicted", "needs_evidence"):
                    sent_back[codes.get(claim) or f"judged {state.replace('_', ' ')}"] += 1
        elif stage == "stall":
            stalls.append(e.get("pattern"))
        elif stage == "step" and action == "block" and str(e.get("note", "")).startswith("protected"):
            protected.append(_short(e.get("target"), 40))
    lines = []
    if excuses:
        lines.append("Excuses rejected: " + ", ".join(_unique(excuses, 3)))
    if sent_back:
        lines.append("Claims sent back: " + ", ".join(f"{c} x{n}" if n > 1 else c for c, n in sent_back.most_common(4)))
    last = []
    if stalls:
        last.append("stalls: " + ", ".join(_unique(stalls, 3)))
    if protected:
        last.append("blocked edits to Hall Monitor's files: " + ", ".join(_unique(protected, 2)))
    if last:
        text = "; ".join(last)
        lines.append(text[0].upper() + text[1:])
    return [l if len(l) <= MAX_LINE else l[:MAX_LINE - 1] + "…" for l in lines[:3]]


def save(store):
    """Summarize the current session and save it to lessons.json (only if the session logged anything).
    Returns the lines, or None if there was nothing to summarize."""
    events = session_events(store)
    if not events:
        return None
    lines = summarize(events)
    store.write_report("lessons.json", json.dumps({"written": now(), "events": len(events), "lines": lines}, indent=2))
    return lines


def brief_lines(store):
    """For the SessionStart briefing, before the new session is logged: the last session's lessons."""
    lines = save(store)
    if lines is None:  # nothing logged since the last session started: use what was saved, if anything
        p = store.dir / "lessons.json"
        lines = json.loads(p.read_text(encoding="utf-8")).get("lines", []) if p.exists() else []
    return ["From your last session:"] + [f"- {l}" for l in lines] if lines else []
