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
    "robustness in real Bob": (0.15, 5, "Real Bob found 12 bugs on Sept 27, all false alarms; all fixed, the last "
                                        "5 not yet re-run in real Bob"),
    "explainability": (0.10, 8, "Hall Pass built from the session's own log; says why a task stopped"),
    "rules and plan": (0.10, 7, "Policy PDF and prompt lines become rules; plan gate on PLAN.md"),
    "drift and stalls": (0.05, 6, "Named stall patterns and checkpoints; one real false stall, fixed"),
    "subagents": (0.05, 7, "Briefs checked before a subagent starts, summaries after it returns"),
    "learning and eval": (0.05, 6, "Seeded eval with a certified threshold; noisy at n=38; control set"),
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
    rounds = [e for e in ev if e.get("stage") == "receipts" and e.get("source") != "stop"] or \
        [e for e in ev if e.get("stage") == "receipts"]
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
    return {"runs": runs, "seeded": load_json(ROOT / "eval" / "summary.json"),
            "control": load_json(ROOT / "eval" / "control_set.json"), "reviewers": len(minutes),
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
    lvl["learning and eval"] = ("E5", f"{ev['reviewers']} review timings") if ev["reviewers"] else \
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
        "reviewers with timings": ev["reviewers"],
    }


def score(ev):
    lvl, rows, total = levels(ev), [], 0.0
    for part, (w, quality, why) in RUBRIC.items():
        level, basis = lvl[part]
        s = min(quality, CAP[level])
        total += w * s
        rows.append((part, w, quality, level, CAP[level], s, basis, why))
    return rows, round(total, 1)


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
