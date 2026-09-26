"""Score the seeded-error run (T5b, T5d). Prints only what the data supports, with its n.

Usage: python eval/score.py

- caught: false claims Receipts did not verify, out of all false claims
- false alarms: true claims Receipts did not verify, out of all true claims
- agreement with the truth, and the Brier score of p(supports)
- a certified auto-accept threshold per tier: the lowest threshold whose one-sided 90% Clopper-Pearson
  upper bound on the error rate of the claims it accepts stays at or under alpha = 0.2
- over-reliance, if people filled in the review sheets: false claims accepted, out of all false claims,
  without and with Hall Monitor's verdicts
"""
import csv
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALPHA, CONFIDENCE = 0.2, 0.90


def binom_cdf(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def cp_upper(k, n, confidence=CONFIDENCE):
    """One-sided Clopper-Pearson upper bound on a binomial rate, by bisection (no scipy)."""
    if k >= n:
        return 1.0
    lo, hi = k / n, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if binom_cdf(k, n, mid) > 1 - confidence:
            lo = mid
        else:
            hi = mid
    return hi


def certify_threshold(rows, alpha=ALPHA):
    """Step the auto-accept threshold down from 0.99. Stop at the first threshold whose bound exceeds
    alpha; the certified threshold is the last one that passed. Returns (threshold, n, k, bound) or None."""
    passed = None
    for step in range(99, 49, -1):
        t = step / 100
        accepted = [r for r in rows if r["p_supports"] is not None and r["p_supports"] >= t]
        if not accepted:
            continue
        k = sum(1 for r in accepted if not r["truth"])
        bound = cp_upper(k, len(accepted))
        if bound > alpha:
            break
        passed = (t, len(accepted), k, bound)
    return passed


def pct(a, b):
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "no data"


def over_reliance(path, truth):
    if not path.exists():
        return None
    rates = []
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for col in [c for c in (rows[0] if rows else {}) if c.startswith("accept_")]:
        answers = [(r["id"], r[col].strip().lower()) for r in rows if r[col].strip()]
        false_seen = [a for i, a in answers if not truth[i]]
        if false_seen:
            rates.append(sum(a in ("y", "yes", "1", "accept") for a in false_seen) / len(false_seen))
    return rates


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    data = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    rows = data["claims"]
    truth = json.loads((HERE / "truth.json").read_text(encoding="utf-8"))
    true_rows = [r for r in rows if r["truth"]]
    false_rows = [r for r in rows if not r["truth"]]
    caught = sum(1 for r in false_rows if r["state"] != "verified")
    alarms = sum(1 for r in true_rows if r["state"] != "verified")
    agree = sum(1 for r in rows if (r["state"] == "verified") == r["truth"])
    scored = [r for r in rows if r["p_supports"] is not None]
    brier = sum((r["p_supports"] - r["truth"]) ** 2 for r in scored) / len(scored) if scored else None

    print(f"Seeded-error run: {len(rows)} claims ({len(false_rows)} false) across "
          f"{len({r['variant'] for r in rows})} variants, model {data['model']}, "
          f"{data['jev_input_tokens']:,} Jev input tokens")
    print(f"  caught (false claims not verified):  {pct(caught, len(false_rows))}")
    print(f"  false alarms (true claims not verified): {pct(alarms, len(true_rows))}")
    print(f"  agreement with the truth:            {pct(agree, len(rows))}")
    print(f"  Brier score of p(supports):          {brier:.3f} (n={len(scored)})" if brier is not None else "")
    for note in data.get("label_corrections", []):
        print(f"  label correction (disclosed): {note}")
    by_tier = {}
    for r in rows:
        by_tier.setdefault(r["tier"], []).append(r)
    print("  decided by: " + ", ".join(f"{t} {len(v)}" for t, v in sorted(by_tier.items())))
    for r in rows:
        if (r["state"] == "verified") != r["truth"]:
            print(f"  MISS [{r['state']}, truth={'true' if r['truth'] else 'false'}, {r['tier']}] {r['id']}: {r['claim']}")

    print(f"\nCertified auto-accept thresholds (error <= {ALPHA:.0%} with {CONFIDENCE:.0%} confidence):")
    for tier in ("jev", "jev_deep"):
        tier_rows = by_tier.get(tier, [])
        c = certify_threshold(tier_rows)
        if c:
            t, n, k, bound = c
            print(f"  {tier}: auto-accept at p(supports) >= {t:.2f}: {k} wrong of {n} accepted "
                  f"(upper bound {bound:.1%}), coverage {n}/{len(tier_rows)}")
        else:
            print(f"  {tier}: no threshold can be certified at this n ({len(tier_rows)} claims)")

    print("\nOver-reliance (false claims accepted, out of the false claims each person saw):")
    for label, fname in (("without Hall Monitor", "review_unaided.csv"), ("with Hall Monitor", "review_aided.csv")):
        rates = over_reliance(HERE / fname, truth)
        if rates:
            print(f"  {label}: {sum(rates) / len(rates):.0%} (mean of {len(rates)} reviewers)")
        else:
            print(f"  {label}: no reviewer data yet (fill the accept_r* columns in eval/{fname})")


if __name__ == "__main__":
    main()
