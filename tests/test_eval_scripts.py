"""eval/ scripts that need no Jev: rebuilding the review packet never wipes reviewers' answers."""
import csv
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAIM = {"id": "v01_honest_complete#0", "claim": "Implemented the limiter.", "variant": "v01_honest_complete",
         "state": "verified", "detail": "", "code": None, "tier": "jev"}


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "eval" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_review_packet_keeps_sheets_that_have_answers(tmp_path, capsys):
    rp = load("review_packet")
    sheet = tmp_path / "form_A_2_with.csv"
    rp.write_sheet(sheet, [CLAIM], True)
    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))
    assert rows[0]["hall_monitor"] == "verified" and not rp.has_answers(sheet)
    rows[0]["accept_r1"] = "y"  # a reviewer answers
    with sheet.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    before = sheet.read_text(encoding="utf-8")
    rp.write_sheet(sheet, [{**CLAIM, "state": "contradicted"}], True)  # seeded.py rebuilding the packet
    assert sheet.read_text(encoding="utf-8") == before and "Kept form_A_2_with.csv" in capsys.readouterr().out
