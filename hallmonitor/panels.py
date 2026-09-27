"""Hall Pass content added in v4.2, kept out of report.write_hall_pass, which calls extra() once.

- Pseudo-tested: functions whose whole body can be replaced without failing a test (mutation.py).
- Deep review: the riskiest files reviewed by explore subagents, when config deep_review is on (review.py).
- Lessons: what this session will tell the next one at SessionStart (lessons.py).
"""
from html import escape

from . import lessons


def _e(x):
    return escape(str(x if x is not None else ""))


def pseudo_tested(receipts):
    sab = (receipts or {}).get("sabotage") or {}
    if not sab.get("extreme_mutants"):
        return ""
    found = sab.get("pseudo_tested") or []
    if found:
        what = " · ".join(f'<span class="target">{_e(p["function"])}</span> (body replaced with '
                          f'<span class="target">{_e(p["body_replaced_with"])}</span>)' for p in found)
        return (f'<tr><td class="stage">pseudo-tested</td><td class="why"><span class="pattern">Pseudo-tested:</span> '
                f'{what}. The tests still pass without these functions.</td></tr>')
    return (f'<tr><td class="stage">pseudo-tested</td><td class="why">Pseudo-tested: none. Each of the '
            f'{sab["extreme_mutants"]} changed functions tried was caught when its body was replaced.</td></tr>')


def deep_review(receipts):
    """Deep review (review.py, off by default): the files requested, or what the reviews found."""
    r = receipts or {}
    if r.get("reviews"):
        files = ", ".join(f'{_e(x["file"])} (risk {_e(x["risk"])})' for x in r["reviews"])
        return (f'<tr><td class="stage">deep review</td><td class="why">Requested for {files}: waiting for Bob\'s '
                f'explore-subagent reviews.</td></tr>')
    rows = ""
    for x in r.get("review") or []:
        p = x.get("defect")
        cls, label = ("bad", "possible defect") if (p or 0) >= 0.5 else ("ok", "no defect") if p is not None \
            else ("warn", "not checked")
        rows += (f'<tr><td class="stage">deep review</td><td><span class="chip {cls}">{label}</span> '
                 f'<span class="target">{_e(x["file"])}</span><div class="why">{_e(x["notes"][:400])}</div></td></tr>')
    return rows


def lessons_html(store):
    lines = lessons.summarize(lessons.session_events(store))
    if not lines:
        return ""
    return ('<h2>For the next session</h2><section><table>' +
            "".join(f'<tr><td class="why">{_e(line)}</td></tr>' for line in lines) +
            '<tr><td class="stage">Hall Monitor opens the next session\'s briefing with these lines.</td></tr>'
            '</table></section>')


def extra(store, receipts):
    """HTML for the v4.2 panels, placed right after the Receipts section."""
    rows = pseudo_tested(receipts) + deep_review(receipts)
    return (f"<section><table>{rows}</table></section>" if rows else "") + lessons_html(store)
