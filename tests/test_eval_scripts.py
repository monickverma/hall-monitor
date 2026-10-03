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


def test_a_kept_real_run_has_no_local_paths_and_no_keys(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("real_run", ROOT / "scripts" / "real_run.py")
    rr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rr)
    runs = tmp_path / "real_runs"
    runs.mkdir()
    (runs / "README.md").write_text("| Folder |\n|---|\n| `old` |\n\n\"Stops\" counts blocks.\n", encoding="utf-8")
    monkeypatch.setattr(rr, "RUNS", runs)
    folder = (tmp_path / "hm-demo").resolve()
    (folder / ".hallmonitor").mkdir(parents=True)
    (folder / ".hallmonitor" / "bob_runs.jsonl").write_text(
        '{"mode": "supervised", "prompt": "x", "stats": {"session_costs": 0.2}}\n', encoding="utf-8")
    (folder / ".hallmonitor" / "events.jsonl").write_text(
        '{"stage": "step", "action": "block", "target": "%s/.bob/mcp.json"}\n' % folder.as_posix(), encoding="utf-8")
    dest, r = rr.keep(folder, "protected-path", rr.TASKS["protected-path"], ["tsk_real_key_value"])
    assert folder.as_posix() not in (dest / ".hallmonitor" / "events.jsonl").read_text(encoding="utf-8")
    assert r["stops"] == 1 and dest.name.endswith("_protected-path_no-receipts")
    readme = (runs / "README.md").read_text(encoding="utf-8")
    assert readme.index(f"`{dest.name}`") < readme.index("\"Stops\"") and readme.endswith("blocks.\n")
    (folder / ".hallmonitor" / "receipts.md").write_text("tsk_real_key_value", encoding="utf-8")
    try:
        rr.keep(folder, "protected-path", rr.TASKS["protected-path"], ["tsk_real_key_value"])
        raise AssertionError("a log holding a key value was kept")
    except SystemExit:
        pass


def test_every_real_run_starts_with_the_policys_rules_recorded(tmp_path):
    """Real Bob re-runs, Sept 27: test-first and wrong-jev-key spent their caps trying to read the policy PDF."""
    import json
    spec = importlib.util.spec_from_file_location("real_run", ROOT / "scripts" / "real_run.py")
    rr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rr)
    assert rr.start_ledger(rr.POLICY_LEDGER, tmp_path) == 5
    ledger = (tmp_path / ".hallmonitor" / "ledger.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(x) for x in ledger.splitlines()]
    assert [r["id"] for r in rows] == ["D1", "D2", "D3", "D4", "D5"]  # the user's rule is the task's to record
    assert all(r["source"].startswith("docs/security-policy.pdf") for r in rows)
    assert all(task[3] == rr.POLICY_LEDGER for name, task in rr.TASKS.items() if name != "decisions")
    assert rr.TASKS["decisions"][3] is None  # that task records the rules itself
    assert (rr.TASKS["subagents"][1], rr.TASKS["test-first"][1]) == ("2.50", "1.20")
