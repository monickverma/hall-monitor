"""Build the review packet for the human pilot: over-reliance and time, with and without Hall Monitor.

Two disjoint sets of 8 seeded claims (4 true, 4 false each). Two forms, counterbalanced:
- Form A: part 1 is set A without Hall Monitor, part 2 is set B with Hall Monitor's verdicts.
- Form B: part 1 is set B without, part 2 is set A with.
So no one judges the same claim twice (which would make the second pass faster for the wrong reason),
and every claim is seen in both conditions across reviewers. Reviewers note their minutes per part.

Usage: python eval/review_packet.py      (reads eval/results.json; no Jev calls)
Writes eval/review/: four sheets, minutes.csv, the diffs the claims are about, and README.md.
"""
import csv
import json
import random
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "review"
REVIEWERS = {"r1": "A", "r2": "B", "r3": "A", "r4": "B"}  # reviewer -> form


def sets(rows, per_set=8, seed=27):
    rng = random.Random(seed)
    true = rng.sample([r for r in rows if r["truth"]], per_set)
    false = rng.sample([r for r in rows if not r["truth"]], per_set)
    a = true[:per_set // 2] + false[:per_set // 2]
    b = true[per_set // 2:] + false[per_set // 2:]
    rng.shuffle(a)
    rng.shuffle(b)
    return {"A": a, "B": b}


def has_answers(path):
    """True if a reviewer has already filled in any accept_* cell of this sheet."""
    if not path.exists():
        return False
    with open(path, encoding="utf-8") as f:
        return any(v.strip() for row in csv.DictReader(f) for k, v in row.items() if k and k.startswith("accept_") and v)


def write_sheet(path, claims, with_hm):
    if has_answers(path):  # never overwrite answers people have entered (seeded.py rebuilds the packet)
        print(f"Kept {path.name}: it already has reviewers' answers.")
        return
    reviewers = [r for r, f in REVIEWERS.items()]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "claim", "diff"] + (["hall_monitor", "reason"] if with_hm else []) +
                   [f"accept_{r}" for r in reviewers])
        for x in claims:
            reason = x["detail"] or (f"reason code: {x['code']}" if x["code"] and x["code"] != "code" else
                                     f"judged by {'code' if x['tier'] == 'code' else 'Jev'} on the diff, "
                                     "a fresh test run and sabotage probes")
            w.writerow([x["id"], x["claim"], f"diffs/{x['variant']}.diff"] +
                       ([x["state"].replace("_", " "), reason] if with_hm else []) + [""] * len(reviewers))


README = """# Review pilot: with and without Hall Monitor

About 15 minutes per person. It measures two things, as a small pilot:
- **over-reliance**: how many false claims a reviewer accepts;
- **time**: minutes per claim.

Both are measured without Hall Monitor and with it.

## What you do
1. Find your form. Reviewers r1 and r3 use **Form A**; r2 and r4 use **Form B**.
2. Open part 1, `form_<X>_1_without.csv`. Start a timer. For each claim, read the diff file it points to
   (in `diffs/`) and decide: would you accept this claim about this change, as written? Put `y` or `n`
   in your `accept_rN` column.
3. Stop the timer and write your minutes in `minutes.csv`.
4. Do the same for part 2, `form_<X>_2_with.csv`. It shows Hall Monitor's verdict and reason for each
   claim. Hall Monitor can be wrong, so judge the claim yourself.
5. Don't look at part 2 before finishing part 1, and don't compare answers with anyone.

The claims come from seeded variants of the demo task. Some are false on purpose.

## Then
`python eval/score.py` reports over-reliance and minutes per claim, each with its number of reviewers.
Quote it as a pilot with its n, not as a general result.
"""


def main():
    rows = json.loads((HERE / "results.json").read_text(encoding="utf-8"))["claims"]
    s = sets(rows)
    OUT.mkdir(exist_ok=True)
    (OUT / "diffs").mkdir(exist_ok=True)
    for x in s["A"] + s["B"]:
        src = HERE / "work" / f"{x['variant']}.diff"
        if src.exists():
            shutil.copyfile(src, OUT / "diffs" / f"{x['variant']}.diff")
    write_sheet(OUT / "form_A_1_without.csv", s["A"], False)
    write_sheet(OUT / "form_A_2_with.csv", s["B"], True)
    write_sheet(OUT / "form_B_1_without.csv", s["B"], False)
    write_sheet(OUT / "form_B_2_with.csv", s["A"], True)
    minutes = OUT / "minutes.csv"
    if not minutes.exists():  # never overwrite times people have entered
        with open(minutes, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["reviewer", "form", "part", "minutes"])
            for r, form in REVIEWERS.items():
                w.writerow([r, form, "1_without", ""])
                w.writerow([r, form, "2_with", ""])
    (OUT / "README.md").write_text(README, encoding="utf-8")
    missing = [x["variant"] for x in s["A"] + s["B"] if not (OUT / "diffs" / f"{x['variant']}.diff").exists()]
    print(f"Review packet in {OUT}: 2 forms x 2 parts of 8 claims, minutes.csv, "
          f"{len(list((OUT / 'diffs').glob('*.diff')))} diffs" + (f"; MISSING diffs: {missing}" if missing else ""))


if __name__ == "__main__":
    main()
