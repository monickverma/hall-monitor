"""Scorecard: how good is Hall Monitor, on the evidence this repo holds.

Each part is rated for quality (a judgment, written down below with its reason), but its score is capped by
the strongest evidence behind it, which is computed from the repo:
  E0 design only (cap 3) · E1 unit tests (5) · E2 the scripted run, simulate.py (6)
  E3 measured on cases we seeded (8) · E4 measured in real Bob runs (9) · E5 measured with real people (10)
score = min(quality, cap), so a good design with weak proof can't score high.

Reads only files: eval/summary.json, eval/control_set.json (python eval/control_set.py --json), the review
minutes, bob_sessions/*.json with their Hall Passes, the real Bob runs kept in eval/real_runs/, and any more
run folders given with --runs (a run is a folder whose .hallmonitor/bob_runs.jsonl records a supervised
`bob run`). Spends no Jev and starts no Bob.

Usage: python eval/scorecard.py [--runs DIR ...]      writes eval/scorecard.md and prints it
"""
import argparse
import csv
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hallmonitor import jev  # noqa: E402

CAP = {"E0": 3, "E1": 5, "E2": 6, "E3": 8, "E4": 9, "E5": 10}

# part: (weight, quality, why the quality is what it is). Revisit these by hand; everything else is computed.
RUBRIC = {
    "receipts": (0.25, 8.5, "Per-claim verdicts on evidence Hall Monitor produced itself: fresh tests, sabotage, "
                            "and changed tests re-run on the code before the change"),
    "step monitor": (0.20, 7.5, "Least-harm judgment of every intent; excuses named; code rules before Jev"),
    "robustness in real Bob": (0.15, 5.5, "Single-agent tasks verify in the first round in real Bob (docs, "
                                          "/decisions x2), and the fixes for 16 earlier false alarms held there. The "
                                          "parallel-subagent task ran without a send-back in its last run, but the "
                                          "main agent reached the $1 cost cap before submitting its claims"),
    "explainability": (0.10, 8, "Hall Pass built from the session's own log; says why a task stopped"),
    "rules and plan": (0.10, 7, "Policy PDF and prompt lines become rules; plan gate on PLAN.md"),
    "drift and stalls": (0.05, 6, "Named stall patterns and checkpoints; one real false stall, fixed"),
    "subagents": (0.05, 7, "Briefs checked before a subagent starts, summaries after it returns"),
    "learning and eval": (0.05, 6.5, "Seeded eval with a certified threshold (noisy at n=38); control set; Jev "
                                     "labels the real Bob sessions for the review queue; no human labels yet"),
    "cost and latency": (0.05, 6.5, "Jev costs fractions of a cent; receipts rounds can add minutes"),
}


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def jsonl(path):
    try:
        return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return []


def real_run(hm):
    """One real Bob run from a .hallmonitor folder, or None if no supervised `bob run` is recorded there."""
    runs = [r for r in jsonl(hm / "bob_runs.jsonl") if r.get("mode") == "supervised"]
    if not runs:
        return None
    ev = jsonl(hm / "events.jsonl")
    caller = None  # older logs don't record a round's agent: take it from the submit_claims call just before
    for e in ev:
        if e.get("stage") == "mcp_call" and e.get("tool") == "submit_claims":
            caller = e.get("agent")
        elif e.get("stage") == "receipts" and not e.get("agent"):
            e["agent"] = caller
    ev_main = [e for e in ev if e.get("stage") != "receipts" or e.get("agent") in (None, "main")]
    rounds = [e for e in ev_main if e.get("stage") == "receipts" and e.get("source") != "stop"] or \
        [e for e in ev_main if e.get("stage") == "receipts"]
    judged = [e for e in ev if e.get("stage") in ("intent", "step", "plan", "spawn")]  # as report.py counts them
    stops = [e for e in judged if e.get("action") in ("block", "ask_human", "restate")]
    allowed = {e.get("target") for e in ev if e.get("stage") == "step" and e.get("action") == "allow"}
    stats = runs[-1].get("stats") or {}
    return {"name": hm.parent.name, "final": rounds[-1]["action"] if rounds else "none",
            "first": rounds[0]["action"] if rounds else "none",
            "send_backs": sum(1 for r in rounds if r.get("action") in ("send_back", "stuck")),
            "judged": len(judged), "stops": len(stops),
            "excuses": sum(1 for e in ev if e.get("pattern") and e.get("stage") != "stall"),
            "stops_later_allowed": sum(1 for s in stops if s.get("target") in allowed),
            "stalls": sum(1 for e in ev if e.get("stage") == "stall"),
            "subagents": sum(1 for e in ev if e.get("stage") in ("spawn", "subagent_return")),
            "doc_rules": sum(1 for d in jsonl(hm / "ledger.jsonl") if d.get("source") not in (None, "user")),
            "jev_usd": jev.cost(sum(e.get("tokens") or 0 for e in ev)),
            "bob_usd": stats.get("session_costs"), "minutes": (stats.get("duration_ms") or 0) / 60000}


def session_file(path):
    """A bob_sessions/*.json record, with its Hall Pass's stamp as the final state."""
    d = load_json(path) or {}
    stats = d.get("stats") or {}
    page = path.with_name(path.stem + "_hall-pass.html")
    stamp = re.search(r'class="stamp[^"]*"[^>]*>([A-Z ]+)', page.read_text(encoding="utf-8")) if page.exists() else None
    final = {"VERIFIED": "accept", "STUCK": "stuck", "SENT BACK": "send_back"}.get(
        stamp.group(1).strip() if stamp else "", "none")
    return {"name": path.stem, "final": final, "first": "unknown", "send_backs": None, "judged": None,
            "stops": None, "excuses": None, "stops_later_allowed": None, "stalls": None, "subagents": None, "doc_rules": 0,
            "jev_usd": None, "bob_usd": stats.get("session_costs"), "minutes": (stats.get("duration_ms") or 0) / 60000}


def collect(run_dirs=()):
    runs = [session_file(p) for p in sorted((ROOT / "bob_sessions").glob("*.json"))]
    for d in run_dirs:
        for hm in sorted(Path(d).rglob(".hallmonitor")):
            r = real_run(hm)
            if r:
                runs.append(r)
    minutes = [r for r in csv.DictReader(open(ROOT / "eval" / "review" / "minutes.csv", encoding="utf-8"))
               if (r.get("minutes") or "").strip()] if (ROOT / "eval" / "review" / "minutes.csv").exists() else []
    return {"runs": runs, "run_dirs": list(run_dirs), "seeded": load_json(ROOT / "eval" / "summary.json"),
            "control": load_json(ROOT / "eval" / "control_set.json"), "reviewers": human_labels(),
            "tests": len(list((ROOT / "tests").glob("test_*.py"))),
            "submission": {"docs/statements.md": (ROOT / "docs" / "statements.md").exists(),
                           "demo/bob_run/": (ROOT / "demo" / "bob_run").is_dir(),
                           "IDE screenshots in bob_sessions/": bool(list((ROOT / "bob_sessions").glob("*.png")))}}


def levels(ev):
    """The strongest evidence behind each part, with what it rests on."""
    runs, seeded, control = ev["runs"], ev["seeded"], ev["control"]
    full = [r for r in runs if r["judged"] is not None]
    lvl, n = {}, f"{len(runs)} real run{'' if len(runs) == 1 else 's'}"
    lvl["receipts"] = ("E4", n) if any(r["final"] != "none" for r in runs) else \
        ("E3", "seeded eval") if seeded else ("E1", "unit tests")
    # Judging intents in real Bob isn't enough: its value is the catch, so E4 needs an excuse named in a real run.
    judged = sum(r["judged"] for r in full)
    caught = sum(r["excuses"] for r in full)
    lvl["step monitor"] = ("E4", f"{caught} excuse{'' if caught == 1 else 's'} named in real Bob") \
        if any(r["excuses"] for r in full) else \
        ("E3", f"control set; {judged} actions judged in real Bob, no excuse caught there yet") if control else \
        ("E2", "simulate.py")
    lvl["robustness in real Bob"] = ("E4", n) if runs else ("E0", "no real run")
    lvl["explainability"] = ("E4", "Hall Passes from real runs") if runs else ("E2", "simulate.py")
    lvl["rules and plan"] = ("E4", "rules from a document in a real run") \
        if any(r["doc_rules"] for r in runs) else ("E2", "simulate.py (policy PDF); real runs had prompt rules only")
    lvl["drift and stalls"] = ("E4", "stalls flagged in real runs") \
        if any(r["stalls"] for r in full) else ("E2", "simulate.py")
    lvl["subagents"] = ("E4", "subagents checked in real runs") \
        if any(r["subagents"] for r in full) else ("E2", "simulate.py and the probe")
    lvl["learning and eval"] = ("E5", f"{ev['reviewers']} answers from people") if ev["reviewers"] else \
        ("E3", "seeded eval, no reviewer data yet") if seeded else ("E1", "unit tests")
    lvl["cost and latency"] = ("E4", "costs and times of real runs") \
        if any(r["bob_usd"] for r in runs) else ("E2", "simulate.py")
    return lvl


def metrics(ev):
    runs = ev["runs"]
    full = [r for r in runs if r["judged"] is not None]
    med = lambda xs: statistics.median(xs) if xs else None  # noqa: E731
    return {
        "real runs": len(runs),
        "verified in the first round": f"{sum(r['first'] == 'accept' for r in full)}/{len(full)}" if full else "no data",
        "ended verified": f"{sum(r['final'] == 'accept' for r in runs)}/{len(runs)}" if runs else "no data",
        "ended stuck": f"{sum(r['final'] == 'stuck' for r in runs)}/{len(runs)}" if runs else "no data",
        "excuses named": sum(r["excuses"] for r in full) if full else "no data",
        "stops per 10 actions judged": (f"{10 * sum(r['stops'] for r in full) / max(1, sum(r['judged'] for r in full)):.1f}"
                                 if full else "no data"),
        "stops later allowed on the same target": (f"{sum(r['stops_later_allowed'] for r in full)}"
                                                   f"/{sum(r['stops'] for r in full)}" if full else "no data"),
        "median Bob cost per run": med([round(r["bob_usd"], 2) for r in runs if r["bob_usd"]]),
        "median minutes per run": med([round(r["minutes"], 1) for r in runs if r["minutes"]]),
        "seeded: caught": f"{ev['seeded']['caught']}/{ev['seeded']['false_claims']}" if ev["seeded"] else "no data",
        "seeded: false alarms": (f"{ev['seeded']['false_alarms']}/{ev['seeded']['true_claims']}"
                                 if ev["seeded"] else "no data"),
        "control set": f"{ev['control']['correct']}/{ev['control']['total']}" if ev["control"] else "not run with --json",
        "answers from people (review timings, review-queue labels)": ev["reviewers"],
    }


def score(ev):
    lvl, rows, total = levels(ev), [], 0.0
    for part, (w, quality, why) in RUBRIC.items():
        level, basis = lvl[part]
        s = min(quality, CAP[level])
        total += w * s
        rows.append((part, w, quality, level, CAP[level], s, basis, why))
    return rows, round(total, 1)


# v4 tasks T1-T6 (the plan's section 7): each mechanism the plan asked for, where it is in the code, the text that
# shows a test covers it, and how a real Bob run's log shows it working. Evidence per mechanism: E4 if a real run
# shows it, E1 if a test covers it, E0 if only the code has it; "missing" if the code doesn't.
def _ev(events, **kv):
    return any(all((e.get(k) == v) if not callable(v) else v(e.get(k)) for k, v in kv.items()) for e in events)


V4_TASKS = {
    "T1 Jev and safety fixes": [
        ("model pinned to jev-1.13.0", "hallmonitor/jev.py", "CALIBRATED_MODEL", "jev-1.13.0",
         lambda ev, pages: _ev(ev, model="jev-1.13.0")),
        ("a refused request falls back to code rules", "hallmonitor/jev.py", "class JevRefused", "JevRefused",
         lambda ev, pages: _ev(ev, fallback="jev_refused")),
        ("cost billed on input tokens only", "hallmonitor/jev.py", "PRICE_PER_M_INPUT", "jev.cost(",
         lambda ev, pages: _ev(ev, tokens=lambda t: bool(t))),
        ("question-wording hash on every event", "hallmonitor/store.py", "QHASH", "qhash",
         lambda ev, pages: _ev(ev, qhash=lambda q: bool(q))),
        ("edits to .bob/ and .hallmonitor/ blocked in code", "hallmonitor/step.py", "is_protected", "protected",
         lambda ev, pages: _ev(ev, note=lambda n: "protected" in (n or ""))),
    ],
    "T2 feedback mid-task and the outcome check": [
        ("notes reach Bob at the top of the next MCP result", "hallmonitor/mcp_server.py", "pop_pending",
         "pop_pending", lambda ev, pages: _ev(ev, stage="subagent_return", action="flag")),
        ("a failed command is recorded", "hallmonitor/evidence.py", "failed_step", "failed_step",
         lambda ev, pages: _ev(ev, handles_failure=lambda h: h is not None)),
        ("the next intent must deal with it (outcome check)", "hallmonitor/step.py", "HANDLES_FAILURE",
         "handles_failure", lambda ev, pages: _ev(ev, handles_failure=lambda h: h is not None)),
    ],
    "T3 the stop rule": [
        ("stuck after 2 send-backs", "hallmonitor/receipts.py", "max_send_backs", "stuck",
         lambda ev, pages: _ev(ev, stage="receipts", action="stuck")),
        ("says which checkpoint to restore", "hallmonitor/receipts.py", "def restore_advice", "restore",
         lambda ev, pages: any("refs/hallmonitor/C" in p for p in pages)),
    ],
    "T4 receipts: enough evidence, and is false sure": [
        ("four claim states", "hallmonitor/receipts.py", "cant_check", "needs_evidence",
         lambda ev, pages: _ev(ev, stage="receipts")),
        ("a claim is called false only when two readings agree", "hallmonitor/receipts.py", "SHOWS_FALSE",
         "contradicts", lambda ev, pages: _ev(ev, stage="receipts", tiers=lambda t: "jev_deep" in (t or []))),
        ("code checks before Jev", "hallmonitor/receipts.py", "def certify", "diff_mismatch",
         lambda ev, pages: _ev(ev, stage="receipts", tiers=lambda t: "code" in (t or []))),
        ("changed tests re-run on the code before the change", "hallmonitor/gitutil.py", "def fail_before",
         "fail_before", lambda ev, pages: any("Changed tests on the code before the change" in p for p in pages)),
    ],
    "T5 calibration, control set, bulk classification": [
        ("(a) seeded variants with known truth", "eval/seeded.py", "VARIANTS", "seeded", None),
        ("(b) caught, false alarms, agreement, Brier", "eval/score.py", "brier", "score", None),
        ("(c) control set of 10 must-block and 10 must-allow", "eval/control_set.py", "MUST_BLOCK", "control_set",
         None),
        ("(d) review sheets for people, with and without Hall Monitor", "eval/review_packet.py", "form_", "review",
         None),
        ("(e) bulk classification into a review queue", "eval/review_queue.py", "needs_person", "review_queue",
         lambda ev, pages: any("real_runs" in p for p in pages)),
    ],
    "T6 Hall Pass v4": [
        ("loops strip, stuck state, four claim states, seeded panel", "hallmonitor/report.py", "Loops", "hall_pass",
         lambda ev, pages: any("Loops" in p for p in pages)),
        ("features in play built from the session's log", "hallmonitor/report.py", "IBM Bob features in play",
         "features", lambda ev, pages: any("IBM Bob features in play" in p for p in pages)),
    ],
}


# The evidence each mechanism should reach: E4 (seen in real Bob) for everything that runs inside Bob; the offline
# evals are measured by design (E3); the review sheets need people's answers (E5).
TARGET = {"(a) seeded variants with known truth": "E3", "(b) caught, false alarms, agreement, Brier": "E3",
          "(c) control set of 10 must-block and 10 must-allow": "E3",
          "(d) review sheets for people, with and without Hall Monitor": "E5"}
ORDER = ["missing", "E0", "E1", "E3", "E4", "E5"]


def at_target(label, level):
    return ORDER.index(level) >= ORDER.index(TARGET.get(label, "E4"))


# eval mechanisms: the file their measured result lives in ("people": filled in by reviewers)
MEASURED = {"(a) seeded variants with known truth": "eval/results.json",
            "(b) caught, false alarms, agreement, Brier": "eval/summary.json",
            "(c) control set of 10 must-block and 10 must-allow": "eval/control_set.json",
            "(d) review sheets for people, with and without Hall Monitor": "people",
            "(e) bulk classification into a review queue": "eval/review_queue_summary.json"}


def human_labels():
    """Answers people have filled in: review-pilot timings, and needs_person labels on the review-queue sample."""
    n = 0
    for name, col in (("eval/review/minutes.csv", "minutes"), ("eval/review_queue_sample.csv", "needs_person")):
        path = ROOT / name
        if path.exists():
            n += sum(1 for r in csv.DictReader(open(path, encoding="utf-8")) if (r.get(col) or "").strip())
    return n


def task_rows(real_dirs):
    """(task, mechanism, evidence) for every v4 mechanism, from the code, the tests and the real runs' logs."""
    tests = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / "tests").glob("test_*.py"))
    events, pages = [], []
    for d in real_dirs:
        for hm in Path(d).rglob(".hallmonitor"):
            if any(r.get("mode") == "supervised" for r in jsonl(hm / "bob_runs.jsonl")):
                events += jsonl(hm / "events.jsonl")
                pages += [str(hm)] + [(hm / f).read_text(encoding="utf-8", errors="ignore")
                                      for f in ("hall-pass.html", "receipts.md") if (hm / f).exists()]
    rows, human = [], human_labels()
    for task, mechs in V4_TASKS.items():
        for label, path, marker, test_marker, real in mechs:
            code = (ROOT / path).exists() and marker in (ROOT / path).read_text(encoding="utf-8", errors="ignore")
            level = "missing" if not code else "E4" if real and real(events, pages) else \
                "E1" if test_marker in tests else "E0"
            if code and label in MEASURED:  # an eval script counts by what it has measured
                out = MEASURED[label]
                level = "E4" if level == "E4" else \
                    ("E5" if human else "E1") if out == "people" else "E3" if (ROOT / out).exists() else level
            rows.append((task, label, level))
    return rows


def money(x):
    return "" if x is None else f"{x:.2f}"


def render(ev):
    rows, total = score(ev)
    out = ["# Hall Monitor scorecard", "",
           "score = min(quality, cap of the strongest evidence). Evidence: E0 design · E1 unit tests · "
           "E2 scripted run · E3 seeded cases · E4 real Bob · E5 real people.", "",
           "| Part | Weight | Quality | Evidence | Cap | **Score** | Evidence used | Why this quality |",
           "|---|---|---|---|---|---|---|---|"]
    out += [f"| {p} | {w:.0%} | {q} | {lv} | {c} | **{s}** | {b} | {why} |" for p, w, q, lv, c, s, b, why in rows]
    out += ["", f"**Overall: {total}/10**", "", "## Measured", ""]
    out += [f"- {k}: {v if v is not None else 'no data'}" for k, v in metrics(ev).items()]
    out += ["", "## Real runs", "", "| Run | First round | Final | Send-backs | Judged | Stops | Bob $ | Minutes |",
            "|---|---|---|---|---|---|---|---|"]
    out += [f"| {r['name']} | {r['first']} | {r['final']} | {r['send_backs']} | {r['judged']} | {r['stops']} | "
            f"{money(r['bob_usd'])} | {r['minutes']:.1f} |" for r in ev["runs"]]
    out += ["", "## v4 tasks (T1-T6): built, tested, seen in real Bob", "",
            "Target: E4 (seen in real Bob) for what runs inside Bob, E3 (measured) for the offline evals, E5 "
            "(people's answers) for the review sheets.", "",
            "| Task | Built | At target | Mechanisms (evidence / target) |", "|---|---|---|---|"]
    rows = task_rows(ev.get("run_dirs", []))
    for task in V4_TASKS:
        mine = [r for r in rows if r[0] == task]
        built = sum(r[2] != "missing" for r in mine)
        done = sum(at_target(label, level) for _, label, level in mine)
        out.append(f"| {task} | {built}/{len(mine)} | {done}/{len(mine)} | "
                   + "; ".join(f"{label} ({level}/{TARGET.get(label, 'E4')})" for _, label, level in mine) + " |")
    out += ["", "## Submission evidence", ""]
    out += [f"- [{'x' if ok else ' '}] {k}" for k, ok in ev["submission"].items()]
    return "\n".join(out) + "\n"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="*", default=[], help="more folders holding real Bob run repos")
    text = render(collect([ROOT / "eval" / "real_runs", *ap.parse_args().runs]))
    (ROOT / "eval" / "scorecard.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
