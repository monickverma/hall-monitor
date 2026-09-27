"""Deep review (v4.2, F3), behind config deep_review (default false).

When it is on and every claim verifies, Receipts asks for a review of the riskiest changed files before
the task counts as done: status REVIEW, for at most 3 files that Jev rated FILE_RISK >= 2.2 (the files
Receipts already reports as risky). Bob reviews each one with a parallel read-only `explore` subagent,
then calls submit_claims again with the same claims and review_notes {file: findings}.

Once every requested file has notes, the round is accepted and the findings go to the user (Bob's
message, receipts.md, the Hall Pass). One Jev question per file marks the findings that report a
concrete defect, so those come first. Findings never turn a verified claim into a failed one: a person
decides what to do with them. The question is new and uncalibrated, which is one reason this is off by
default.
"""
import json
import time

from typesafe_sdk import Noul

from . import jev, receipts
from .store import rel_path

MAX_FILES = 3

REPORTS_DEFECT = Noul(
    instructions=("`review` is an independent reviewer's findings about the changed file `file`. Does it report a "
                  "concrete defect in that file: a bug, a security problem, or a break of one of `decisions`?"),
    criteria={"true": "Reports at least one concrete defect in the file",
              "false": "Finds no defect, or only style remarks and suggestions"},
)


def requested(result):
    """The files to review: the riskiest changed files, highest risk first, at most MAX_FILES."""
    return [f for f, _ in sorted(result.get("risky_files") or [], key=lambda x: -x[1])][:MAX_FILES]


def brief(store, file, risk):
    rules = "; ".join(f"{d['id']}: {d['text']}" for d in store.active_decisions())
    return (f"Review {file} independently; Hall Monitor rated the risk of this change {risk} on a 0-3 scale. "
            "Read the file and the tests that cover it, and do not edit anything. Look for bugs, security "
            "problems" + (f" and breaks of the project rules ({rules})" if rules else "") +
            ". Report each finding with file:line, or say plainly that you found none.")


def judge(store, notes):
    """p(the review reports a defect) per file; a refused request leaves that file unjudged."""
    decisions = {d["id"]: d["text"] for d in store.active_decisions()}
    files = list(notes)
    results = jev.ask_many([({"file": f, "review": notes[f], "decisions": decisions}, {"defect": REPORTS_DEFECT})
                            for f in files], return_refusals=True)
    found, tok = {}, 0
    for f, r in zip(files, results):
        if not isinstance(r, jev.JevRefused):
            found[f], tok = r[0]["defect"]["noul"], tok + jev.tokens(r[1])
    return found, tok


def section(result):
    """The deep review part of receipts.md."""
    if result.get("reviews"):
        return "\n## Deep review requested\n\n" + "".join(f"- {r['file']} (risk {r['risk']})\n" for r in result["reviews"])
    if result.get("review"):
        return "\n## Deep review\n\n" + "".join(
            f"- {r['file']}: {'possible defect' if (r['defect'] or 0) >= 0.5 else 'no defect reported' if r['defect'] is not None else 'not checked'}"
            f" ({r['notes'][:300]})\n" for r in result["review"])
    return ""


def after_verify(store, result, review_notes=None):
    """Receipts' result, plus the deep review step when config deep_review is on and all claims verified."""
    if not store.config().get("deep_review") or result["status"] != "accept":
        return result
    files = requested(result)
    if not files:
        return result
    t0, risk = time.time(), dict(result["risky_files"])
    given = review_notes if isinstance(review_notes, dict) else {}
    notes = {rel_path(store.root, f): str(v)[:3000] for f, v in given.items() if str(v).strip()}
    todo = [f for f in files if f not in notes]
    if todo:
        result = {**result, "status": "review",
                  "reviews": [{"file": f, "risk": risk[f], "brief": brief(store, f, risk[f])} for f in todo]}
        store.log({"stage": "review", "action": "review", "target": ", ".join(todo)})
    else:
        found, tok = judge(store, {f: notes[f] for f in files})
        result = {**result, "review": [{"file": f, "risk": risk[f], "notes": notes[f], "defect": found.get(f)}
                                       for f in files]}
        flagged = [f for f in files if (found.get(f) or 0) >= 0.5]
        store.log({"stage": "review", "action": "flag" if flagged else "accept", "target": ", ".join(files),
                   "flagged": flagged, "tokens": tok, "ms": int((time.time() - t0) * 1000)})
    store.write_report("receipts.json", json.dumps(result, indent=2))
    store.write_report("receipts.md", receipts.report(result) + section(result))
    return result


def message(result):
    """What Bob sees. With deep review off (or nothing to review) this is exactly receipts.message."""
    if result["status"] == "review":
        out = [f"Receipts: all {len(result['rows'])} claims verified. Deep review is on, so before this counts as "
               "done, review the riskiest changed files: spawn one read-only `explore` subagent per file, in "
               "parallel, with these briefs."]
        out += [f"REVIEW NEEDED for {r['file']}:\n{r['brief']}" for r in result["reviews"]]
        out.append("Then call submit_claims again with the same claims and review_notes "
                   "{\"<file>\": <that subagent's findings>} for every file above.")
        return "\n".join(out)
    out = [receipts.message(result)]
    if result.get("review"):
        flagged = [r for r in result["review"] if (r["defect"] or 0) >= 0.5]
        if flagged:
            out.append("Deep review reports possible defects. Tell the user before you finish: " +
                       "; ".join(f"{r['file']}: {r['notes'][:200]}" for r in flagged))
        else:
            out.append(f"Deep review of {', '.join(r['file'] for r in result['review'])}: no defects reported.")
    return "\n".join(out)
