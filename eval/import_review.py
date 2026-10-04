"""Import reviewers' answers from the review-pilot page into the review sheets.

The page (claude.ai artifact "Hall Monitor Review Pilot") keeps one document per reviewer in its `answers` collection:
{slot: "r1".."r4", form: "A"|"B", parts: {"1_without"|"2_with": {started, finished, answers: {claim id: "y"|"n"}}},
queue: {event key: "y"|"n"}}. Save them with the ArtifactData tool (`list`, collection `answers`, `out_dir`), then:

  python eval/import_review.py DIR [--force]

It fills accept_rN in eval/review/form_<X>_<part>.csv, the minutes in eval/review/minutes.csv (from the page's own
timer) and needs_person in eval/review_queue_sample.csv. A cell that already holds an answer is left alone unless
--force. Only finished parts are imported. Then run: python eval/score.py, python eval/scorecard.py
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_docs(folder):
    docs = []
    for p in sorted(Path(folder).rglob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        d = d.get("data") if isinstance(d.get("data"), dict) else d  # a saved {id, data, version} or the bare body
        if isinstance(d, dict) and d.get("slot") in ("r1", "r2", "r3", "r4"):
            docs.append(d)
    return docs


def _rewrite(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _fill(cell, value, force):
    return value if force or not (cell or "").strip() else cell


def import_answers(docs, root=ROOT, force=False):
    """Returns counts of what was written. Raises SystemExit when two documents claim the same slot."""
    slots = [d["slot"] for d in docs]
    dupes = sorted({s for s in slots if slots.count(s) > 1})
    if dupes:
        raise SystemExit(f"More than one reviewer used slot {', '.join(dupes)}: sort it out with them, then re-import.")
    review = Path(root) / "eval" / "review"
    n = {"answers": 0, "minutes": 0, "labels": 0}
    for d in docs:
        slot, form = d["slot"], d.get("form")
        for part, p in (d.get("parts") or {}).items():
            if not p.get("finished"):
                continue  # an unfinished part has no timing and may be half answered
            path = review / f"form_{form}_{part}.csv"
            with open(path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fields, rows = reader.fieldnames, list(reader)
            for r in rows:
                v = (p.get("answers") or {}).get(r["id"])
                if v in ("y", "n"):
                    r[f"accept_{slot}"] = _fill(r.get(f"accept_{slot}"), v, force)
                    n["answers"] += 1
            _rewrite(path, fields, rows)
            mpath = review / "minutes.csv"
            with open(mpath, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                mfields, mrows = reader.fieldnames, list(reader)
            for r in mrows:
                if r["reviewer"] == slot and r["part"] == part:
                    r["minutes"] = _fill(r.get("minutes"), f"{(p['finished'] - p['started']) / 60000:.1f}", force)
                    n["minutes"] += 1
            _rewrite(mpath, mfields, mrows)
    qpath = Path(root) / "eval" / "review_queue_sample.csv"
    with open(qpath, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        qfields, qrows = reader.fieldnames, list(reader)
    for r in qrows:  # the first reviewer (by slot) to label an event wins; others' labels are counted, not merged
        for d in sorted(docs, key=lambda d: d["slot"]):
            v = (d.get("queue") or {}).get(r["key"])
            if v in ("y", "n") and not (r.get("needs_person") or "").strip():
                r["needs_person"] = v
                n["labels"] += 1
    _rewrite(qpath, qfields, qrows)
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder", help="the folder the ArtifactData list saved the answers documents into")
    ap.add_argument("--force", action="store_true", help="overwrite answers already in the sheets")
    a = ap.parse_args()
    docs = load_docs(a.folder)
    if not docs:
        sys.exit(f"No reviewer documents (with a slot) under {a.folder}.")
    print(f"{len(docs)} reviewer(s): {', '.join(sorted(d['slot'] for d in docs))}")
    print(import_answers(docs, force=a.force))


if __name__ == "__main__":
    main()
