"""Fabricated files (v4.2): a claim about a code file that exists nowhere is contradicted by code, before Jev,
with reason code unknown_file. Jev is a fake."""
import pytest

from conftest import PASSING, FakeJev, git, make_repo
from hallmonitor import evidence as EV, fabricated as FB, jev, receipts, report
from hallmonitor.store import Store

LEDGER = {"E1": {"id": "E1", "kind": "edit", "file": "app/ratelimit.py", "edit_seq": 1},
          "E2": {"id": "E2", "kind": "test", "command": "pytest", "status": "pass", "edit_seq": 1, "tail": "3 passed"}}
PASSED = {"passed": True, "command": "pytest", "tail": ["3 passed"]}


@pytest.fixture
def store(tmp_path):
    return make_repo(tmp_path, {"app/service.py": "def login():\n    return 'ok'\n", "app/old.py": "X = 1\n",
                                "src/pkg/helpers.py": "Y = 2\n", ".gitignore": "build/\n"},
                     config={"test_command": PASSING, "max_mutants": 0, "max_extreme_mutants": 0})


def unknown(store, claim, known=()):
    return FB.unknown_files(store.root, store.session()["base"], claim, set(known))


def test_mentioned_paths_skips_urls_project_names_negations_and_non_code():
    assert FB.mentioned_paths("Added app/validators.py and wired it into app/service.py.") == \
        ["app/validators.py", "app/service.py"]
    assert FB.mentioned_paths("Works on Node.js and Vue.js; see https://example.com/app/x.py.") == []
    assert FB.mentioned_paths("Put the limiter in app/ratelimit.py instead of a new helpers.py.") == ["app/ratelimit.py"]
    assert FB.mentioned_paths("Updated docs/limits.md and config.yaml.") == []
    assert FB.mentioned_paths("Fixed ./app/auth.py.") == ["app/auth.py"]


def test_a_path_that_exists_nowhere_is_unknown(store):
    assert unknown(store, "Added input validation in app/validators.py.") == ["app/validators.py"]
    assert unknown(store, "Added validators.py.") == ["validators.py"]


def test_a_path_that_exists_somewhere_is_known(store):
    root = store.root
    assert unknown(store, "Changed app/service.py.") == []  # tracked
    assert unknown(store, "Moved the helper into pkg/helpers.py and helpers.py.") == []  # a suffix of a tracked path
    (root / "app" / "new.py").write_text("Z = 3\n")
    assert unknown(store, "Created app/new.py.") == []  # untracked, in the working tree
    (root / "build").mkdir()
    (root / "build" / "gen.py").write_text("")
    assert unknown(store, "Generated build/gen.py and gen.py.") == []  # ignored, but on disk
    git(root, "rm", "-q", "app/old.py")
    assert unknown(store, "Removed the dead code in app/old.py.") == []  # deleted: in the diff since the base
    assert unknown(store, "Wrote app/limits.py.", known={"app/limits.py"}) == []  # in an evidence row


def test_certify_contradicts_change_claims_only():
    cert = receipts.certify("implemented", ["E1", "E2"], ["app/ratelimit.py"], {"app/ratelimit.py": {}}, LEDGER,
                            PASSED, unknown=["app/validators.py"])
    assert cert == ("contradicted", "unknown_file", "app/validators.py does not exist in this repo.")
    assert receipts.certify("tests_added", [], [], {}, LEDGER, PASSED, unknown=["tests/a.py", "tests/b.py"])[2] == \
        "tests/a.py, tests/b.py do not exist in this repo."
    assert receipts.certify("unchanged", [], [], {}, LEDGER, PASSED, unknown=["app/x.py"]) is None  # true: never touched
    assert receipts.certify("tests_pass", ["E2"], [], {}, LEDGER, PASSED, unknown=["tests/x.py"]) is None


def test_receipts_catch_a_fabricated_file_in_code_and_show_the_reason(store, monkeypatch):
    fake = FakeJev()
    monkeypatch.setattr(jev, "ask", fake)
    (store.root / "app" / "ratelimit.py").write_text("LIMIT = 5\n")
    EV.record({"tool": "write_file", "input": {"path": "app/ratelimit.py", "content": "LIMIT = 5\n"}}, store)
    EV.record({"tool": "execute_command", "input": {"command": "python -m pytest -q"}, "output": "1 passed"}, store)
    result = receipts.verify(store, [
        {"claim": "Implemented the limiter in app/ratelimit.py.", "evidence": ["E1", "E2"]},
        {"claim": "Added input validation for user names in app/validators.py.", "evidence": ["E2"]}])
    real, fake_file = result["rows"]
    assert real["state"] == "verified"
    assert (fake_file["state"], fake_file["code"], fake_file["tier"]) == ("contradicted", "unknown_file", "code")
    assert fake_file["detail"] == "app/validators.py does not exist in this repo."
    judged = [c for c in fake.calls if "verdict" in c["questions"]]
    assert [c["state"]["claim"] for c in judged] == [real["claim"]]  # Jev never judged the fabricated claim
    assert "[CONTRADICTED, unknown_file]" in receipts.message(result)
    assert "| CONTRADICTED | unknown_file | code |" in (store.dir / "receipts.md").read_text(encoding="utf-8")
    report.write_hall_pass(Store(store.root))
    assert "reason: unknown_file" in (store.dir / "hall-pass.html").read_text(encoding="utf-8")
