"""Bulk classification (T5e): label every event across sessions, rank what a person should review.

Each logged event (an intent, a tool call, a receipts round, a stall...) is summarized in code and sent
to Jev as its own request, at most 8 at once (native API). Batching many events into one request was
measured and rejected: at 10 events per request, 6 of 12 routine steps got a failure form they didn't
show, because neighboring events colored the answers; at one event per request, 0 of 12 did, and all 10
seeded send-back rounds were still labeled correctly. Per event, one request asks both:
- "should a person review this?" (a Noul), which ranks the review queue;
- which of the seven real-world failure forms it shows, if any (a Choice).

Jev's labels are not ground truth. People label a random sample (blind: the sheet doesn't show Jev's
answer), and the rate of events that need a person is then estimated with prediction-powered inference:
Jev's mean over all N events, corrected by the mean human-minus-Jev difference on the n labeled events,
with a 95% interval from both variances (Angelopoulos et al., arXiv 2301.09633).

Usage: python eval/review_queue.py [path/to/.hallmonitor/events.jsonl ...]
With no paths: the demo session (demo/run) and the seeded-eval sessions (eval/work/*).
Writes eval/review_queue.csv (ranked), eval/review_queue_sample.csv (for people),
eval/review_queue_summary.json, and forms.json into each session's .hallmonitor/ folder (the Hall Pass
shows it, and is refreshed).
"""
import csv
import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from hallmonitor import jev, questions as Q, report  # noqa: E402
from hallmonitor.store import Store  # noqa: E402

BATCH, SAMPLE = 1, 30  # events per request (see the docstring for why not more); people label SAMPLE events
SKIP_STAGES = {"mcp_call", "session_start", "error"}


def summarize(ev):
    """One event as a short, self-contained line (code only: no Jev)."""
    bits = [f"{ev.get('stage')}: {ev.get('verdict') or ev.get('action') or ''}"]
    for key in ("tool", "agent", "target", "reason", "pattern", "note", "escalated", "fallback"):
        if ev.get(key) and ev.get(key) != "main":
            bits.append(f"{key}: {str(ev[key])[:160]}")
    bad = {d: p for d, p in (ev.get("violations") or {}).items() if p >= 0.5}
    if bad:
        bits.append(f"may break: {', '.join(bad)}")
    risks = {k: round(v, 2) for k, v in (ev.get("risks") or {}).items() if isinstance(v, (int, float)) and v >= 0.5}
    if risks:
        bits.append(f"risks: {risks}")
    if ev.get("stage") == "receipts":
        states = Counter((ev.get("verdicts") or {}).values())
        bits.append("claims: " + ", ".join(f"{n} {s}" for s, n in states.items()))
        if ev.get("codes"):
            bits.append("reasons: " + ", ".join(sorted(set(ev["codes"].values()))))
        if ev.get("survived"):
            bits.append(f"{ev['survived']}/{ev['mutants']} sabotage mutants survived")
    return "; ".join(bits)[:420]


def ppi(preds_all, labeled):
    """Prediction-powered estimate of a rate: (estimate, low, high) at 95%, or None without labels.
    preds_all: Jev's probability for every event. labeled: [(jev_probability, human 0/1)]."""
    if len(labeled) < 2 or not preds_all:
        return None
    n_all, n = len(preds_all), len(labeled)
    mean_f = sum(preds_all) / n_all
    rect = [y - f for f, y in labeled]
    mean_r = sum(rect) / n
    var_f = sum((f - mean_f) ** 2 for f in preds_all) / max(n_all - 1, 1)
    var_r = sum((r - mean_r) ** 2 for r in rect) / (n - 1)
    est = mean_f + mean_r
    half = 1.96 * math.sqrt(var_f / n_all + var_r / n)
    return est, max(0.0, est - half), min(1.0, est + half)


def load(paths):
    events = []
    for path in paths:
        rows = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
        for k, ev in enumerate(rows):
            if ev.get("stage") not in SKIP_STAGES:
                events.append({"key": f"{Path(path).parent.parent.name}:{k}", "source": str(path), "ev": ev,
                               "summary": summarize(ev)})
    return events


def label(events):
    jobs = []
    for start in range(0, len(events), BATCH):
        chunk = events[start:start + BATCH]
        qs = {}
        for i in range(len(chunk)):
            qs[f"human_{i}"] = Q.needs_human(i)
            qs[f"form_{i}"] = Q.failure_form(i)
        jobs.append(({"events": [e["summary"] for e in chunk]}, qs))
    results = jev.ask_many(jobs)
    tok = 0
    for b, (answers, usage) in enumerate(results):
        tok += jev.tokens(usage)
        for i, e in enumerate(events[b * BATCH:(b + 1) * BATCH]):
            e["p_human"] = answers[f"human_{i}"]["noul"]
            e["form"] = answers[f"form_{i}"]["choice"]
            e["form_confidence"] = answers[f"form_{i}"]["confidence"]
    return tok, len(jobs)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    paths = sys.argv[1:] or [p for p in [ROOT / "demo" / "run" / ".hallmonitor" / "events.jsonl",
                                         *sorted((HERE / "work").glob("*/.hallmonitor/events.jsonl"))] if p.exists()]
    events = load(paths)
    if not events:
        sys.exit("No events found. Run simulate.py or eval/seeded.py first, or pass events.jsonl paths.")
    t0 = time.time()
    tok, requests = label(events)
    secs = time.time() - t0

    ranked = sorted(events, key=lambda e: -e["p_human"])
    with open(HERE / "review_queue.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "key", "p_needs_person", "failure_form", "form_confidence", "summary"])
        for r, e in enumerate(ranked, 1):
            w.writerow([r, e["key"], f"{e['p_human']:.2f}", e["form"], f"{e['form_confidence']:.2f}", e["summary"]])

    # A blind random sample for people. Filled answers are kept if the sheet already exists.
    sample_path = HERE / "review_queue_sample.csv"
    filled = {}
    if sample_path.exists():
        with open(sample_path, encoding="utf-8") as f:
            filled = {r["key"]: r for r in csv.DictReader(f) if r.get("needs_person", "").strip()}
    by_key = {e["key"]: e for e in events}
    keys = [k for k in filled if k in by_key]
    rng = random.Random(27)
    keys += rng.sample([k for k in by_key if k not in filled], max(0, min(SAMPLE, len(by_key)) - len(keys)))
    with open(sample_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "summary", "needs_person", "failure_form"])
        for k in keys:
            old = filled.get(k, {})
            w.writerow([k, by_key[k]["summary"], old.get("needs_person", ""), old.get("failure_form", "")])
    labeled = [(by_key[k]["p_human"], 1 if filled[k]["needs_person"].strip().lower() in ("y", "yes", "1") else 0)
               for k in filled if k in by_key]
    est = ppi([e["p_human"] for e in events], labeled)

    forms = Counter(e["form"] for e in events)
    summary = {"model": jev.MODEL, "events": len(events), "sessions": len(paths), "requests": requests,
               "seconds": round(secs, 1), "jev_input_tokens": tok, "cost": round(jev.cost(tok), 5),
               "jev_rate_needs_person": round(sum(e["p_human"] for e in events) / len(events), 3),
               "ppi": {"estimate": est[0], "low": est[1], "high": est[2], "n": len(labeled)} if est else None,
               "failure_forms_jev": dict(forms.most_common())}
    (HERE / "review_queue_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    for path in paths:  # per-session failure forms, shown on that session's Hall Pass
        session = [e for e in events if e["source"] == str(path)]
        d = Path(path).parent
        (d / "forms.json").write_text(json.dumps({
            "model": jev.MODEL, "events": len(session),
            "forms": dict(Counter(e["form"] for e in session if e["form"] != "none").most_common()),
            "needs_person": sum(1 for e in session if e["p_human"] >= 0.5)}, indent=2), encoding="utf-8")
        if (d / "hall-pass.html").exists():
            report.write_hall_pass(Store(d.parent))

    print(f"Labeled {len(events)} events from {len(paths)} sessions in {requests} Jev requests, {secs:.1f}s, "
          f"{tok:,} input tokens (${jev.cost(tok):.4f}).")
    print(f"Jev says {summary['jev_rate_needs_person']:.0%} of events need a person (Jev labels only).")
    if est:
        print(f"Prediction-powered estimate: {est[0]:.0%} (95% CI {est[1]:.0%}–{est[2]:.0%}), "
              f"from {len(events)} Jev labels corrected by {len(labeled)} human labels.")
    else:
        print(f"No human labels yet: fill needs_person (y/n) in eval/review_queue_sample.csv ({len(keys)} events), "
              "then re-run for the corrected estimate.")
    print("Failure forms (Jev labels):", ", ".join(f"{k} {v}" for k, v in forms.most_common()))
    print("Top of the queue:")
    for e in ranked[:5]:
        print(f"  {e['p_human']:.2f} [{e['form']}] {e['summary'][:110]}")


if __name__ == "__main__":
    main()
