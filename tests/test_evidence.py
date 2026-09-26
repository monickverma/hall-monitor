"""Evidence ledger, checkpoints, stalls, certificate checks and note delivery. No Jev calls."""
import subprocess

import pytest

from hallmonitor import evidence as EV, mcp_server, receipts as R, step
from hallmonitor.store import Store

CFG = {"test_command": "python -m pytest -q"}


def git(root, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=root,
                   check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "app.py").write_text("X = 1\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def post(store, tool, **inp):
    output = inp.pop("output", "")
    EV.record({"event": "PostToolUse", "tool": tool, "input": inp, "output": output}, store)


# ---------------------------------------------------------------- outcome parser

@pytest.mark.parametrize("out,expected", [
    ("....\n5 passed in 0.02s", "pass"),
    ("F...\n1 failed, 4 passed in 0.03s", "fail"),
    ("E\n1 error in 0.1s", "fail"),
    ("Traceback (most recent call last):\n  File ...", "fail"),
    ("'ls' is not recognized as an internal or external command,", "fail"),
    ("python: can't open file 'tools/lint.py': [Errno 2] No such file or directory", "fail"),
    ("Done.", "unknown"),
])
def test_outcome_from_output(out, expected):
    assert EV.outcome(out) == (expected, "inferred")


def test_exit_code_wins_over_output():
    assert EV.outcome("1 failed", exit_code=0) == ("pass", "exit_code")
    assert EV.outcome("5 passed", exit_code=2) == ("fail", "exit_code")


def test_test_commands():
    assert EV.is_test_command("python -m pytest -q tests/x.py", CFG)
    assert EV.is_test_command("pytest", CFG) and EV.is_test_command("npm test", CFG)
    assert not EV.is_test_command("python tools/lint.py", CFG)


# ---------------------------------------------------------------- ledger, checkpoints, stalls

def test_receipts_are_numbered_and_edits_counted(repo):
    store = Store(repo)
    post(store, "write_file", path="app.py", content="X = 2\n")
    post(store, "write_file", path="./PLAN.md", content="# plan")
    rows = store.evidence()
    assert [r["id"] for r in rows] == ["E1", "E2"]
    assert rows[1]["file"] == "PLAN.md" and rows[1]["edit_seq"] == 2
    assert store.session()["edits_since_test"] == 1  # PLAN.md is not code


def test_checkpoint_leaves_tree_index_and_branch_alone(repo):
    (repo / "app.py").write_text("X = 3\n")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    Store(repo)  # creates .hallmonitor/
    cp = EV.gitutil.checkpoint(repo, 1)
    assert cp and cp["ref"] == "refs/hallmonitor/C1"
    shown = subprocess.run(["git", "show", "refs/hallmonitor/C1:app.py"], cwd=repo, capture_output=True, text=True)
    assert shown.stdout == "X = 3\n"
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout == head
    assert subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout == status
    assert EV.gitutil.checkpoint(repo, 2, last_tree=cp["tree"]) is None  # nothing changed since C1


def test_passing_test_run_makes_a_checkpoint_and_a_later_failure_is_a_regression(repo):
    store = Store(repo)
    post(store, "execute_command", command="python -m pytest -q", output="3 passed in 0.01s")
    kinds = [r["kind"] for r in store.evidence()]
    assert kinds == ["test", "checkpoint"]
    post(store, "execute_command", command="python -m pytest -q", output="1 failed, 2 passed")
    s = store.session()
    assert s["stalls"] == 1 and s["failed_step"]["command"] == "python -m pytest -q"
    assert any("Tests passed at checkpoint C1" in n for n in s["notes"])


def test_the_same_failure_twice_is_a_loop(repo):
    store = Store(repo)
    for _ in range(2):
        post(store, "execute_command", command="python tools/lint.py", output="No such file or directory")
    s = store.session()
    assert s["stalls"] == 1 and any("looping on one failure" in n for n in s["notes"])


def test_editing_without_testing_is_a_stall(repo):
    store = Store(repo)
    for i in range(5):
        post(store, "write_file", path="app.py", content=f"X = {i}\n")
    assert store.session()["stalls"] == 1


# ---------------------------------------------------------------- certificate checks

LEDGER = {
    "E1": {"id": "E1", "kind": "edit", "file": "app/ratelimit.py", "edit_seq": 1},
    "E2": {"id": "E2", "kind": "test", "command": "pytest", "status": "pass", "edit_seq": 1, "tail": "3 passed"},
    "E3": {"id": "E3", "kind": "edit", "file": "app/service.py", "edit_seq": 2},
    "E4": {"id": "E4", "kind": "test", "command": "pytest", "status": "fail", "edit_seq": 2, "tail": "1 failed"},
    "E5": {"id": "E5", "kind": "test", "command": "pytest", "status": "pass", "edit_seq": 2, "tail": "3 passed"},
}
CHANGED = {"app/ratelimit.py": {}, "app/service.py": {}}
PASSING = {"passed": True, "command": "pytest", "tail": ["3 passed"]}


def code(kind, cited, named=(), fresh=PASSING, ledger=LEDGER):
    r = R.certify(kind, list(cited), list(named), CHANGED, ledger, fresh)
    return r and r[1]


def test_certificate_reason_codes():
    assert code("implemented", ["E1"], ["app/auth.py"]) == "diff_mismatch"
    assert code("unchanged", [], ["app/service.py"]) == "diff_mismatch"
    assert R.certify("unchanged", [], ["app/auth.py"], CHANGED, LEDGER, PASSING)[0] == "verified"
    assert code("tests_pass", []) == "uncited"
    assert code("tests_pass", ["E9"]) == "unknown"
    assert code("tests_pass", ["E4"]) == "failed"
    assert code("tests_pass", ["E1"]) == "out_of_scope"
    assert code("implemented", ["E1"], ["app/service.py"]) == "out_of_scope"
    assert code("tests_pass", ["E2"]) == "stale"
    assert code("tests_pass", ["E5"], fresh={"passed": False, "command": "pytest", "tail": ["1 failed"]}) \
        == "replay_mismatch"
    assert code("tests_pass", ["E4", "E5"]) is None  # an older failing run is fine (fail before, pass after)
    assert code("implemented", ["E3", "E5"], ["app/service.py"]) is None


def test_send_backs_are_counted_and_a_verified_round_resets():
    assert R.next_round(0, "send_back", 2) == (1, "send_back")
    assert R.next_round(2, "send_back", 2) == (3, "stuck")
    assert R.next_round(2, "needs_evidence", 2) == (2, "needs_evidence")  # the free uncited retry
    assert R.next_round(2, "accept", 2) == (0, "accept")


def test_parse_claims_and_inline_citations():
    parsed = R.parse([{"claim": "A.", "evidence": ["e2", "E2"]}, "B done [E7]."])
    assert parsed == [("A.", ["E2"]), ("B done [E7].", ["E7"])]
    assert R.named_files("Wired it into app/service.py and auth.py.", ["app/service.py", "app/auth.py", "x.py"]) \
        == ["app/auth.py", "app/service.py"]


# ---------------------------------------------------------------- notes reach Bob; protected files

def test_pending_notes_reach_bob_once_through_mcp(repo):
    store = Store(repo)
    store.queue_note("Your last command failed.")
    store.add_flag("A subagent drifted.")
    first = mcp_server.call("list_evidence", {}, store)
    assert first.startswith("Hall Monitor notes before you continue:")
    assert "Your last command failed." in first and "A subagent drifted." in first
    assert not mcp_server.call("list_evidence", {}, store).startswith("Hall Monitor notes")


def test_explain_block_drops_the_short_block_pointer(repo):
    store = Store(repo)
    store.record_block("apply_diff", "app.py", "Hall Monitor blocked this action: because.")
    store.queue_note("Blocked apply_diff on app.py: ... (call explain_block for the full reason)")
    out = mcp_server.call("explain_block", {}, store)
    assert "Blocked apply_diff" not in out and "because." in out


def test_supervisor_files_are_protected_without_asking_jev(repo):
    store = Store(repo)
    for path in (".bob/settings.json", "./.hallmonitor/config.json"):
        code_, _, err = step.pre_tool({"tool": "write_file", "input": {"path": path, "content": "{}"}}, store)
        assert code_ == 2 and "can't be edited" in err
