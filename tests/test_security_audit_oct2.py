"""Fixes from the Oct 2 security audit of Hall Monitor's own enforcement: shell operators that hid a second command,
every way a command can name .bob/ or .hallmonitor/, tools that never reached the hook, and Receipts skipping the
project's rules when a tool left no edit receipt. Jev is a fake."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from conftest import PASSING, FakeJev, make_repo
from hallmonitor import jev, payload as P, receipts, step
import install


@pytest.fixture
def store(tmp_path):
    return make_repo(tmp_path, {"app/service.py": "def login():\n    return 'ok'\n"},
                     config={"test_command": PASSING, "max_mutants": 0, "max_extreme_mutants": 0})


# ---------------------------------------------------------------- shell operators

def test_a_second_command_hidden_behind_an_operator_is_not_safe(store):
    cfg = store.config()
    for c in ("ls & rm -rf app", "cat (Remove-Item app\\auth.py)", "git status & del x", "ls {rm x}",
              "cat x $(rm y)", "ls `rm x`"):
        assert not step.is_safe_command(cfg, c), c


def test_merging_streams_does_not_make_a_test_run_unsafe(store):
    cfg = store.config()
    assert step.is_safe_command(cfg, "python -m pytest -q 2>&1")
    assert not step.is_safe_command(cfg, "python -m pytest -q > out.txt 2>&1")


# ---------------------------------------------------------------- protected folders

PROTECTED_WRITES = (
    "rm -rf .bob", "Remove-Item .hallmonitor\\events.jsonl", "cd .bob && cat mcp.json", "rm .hallmon*", "del .b?b\\x",
    "rm -rf .*", "rm -rf HALLMO~1", "cat x & rm .bob/y", "echo {} > .bob/mcp.json",
    "cat .bob/mcp.json | Set-Content app\\x.py", "python -c \"open('.bob/mcp.json','w')\"",
)


@pytest.mark.parametrize("command", PROTECTED_WRITES)
def test_a_command_that_could_change_a_protected_folder_is_stopped(store, command):
    assert step.touches_protected(command), command
    code, _, err = step.pre_tool({"tool": "execute_command", "input": {"command": command}}, store)
    assert code == 2 and ".bob/ or .hallmonitor/" in err


def test_reading_a_protected_folder_is_still_allowed(store):
    for c in ("cat .bob/mcp.json", "ls .hallmon*", "Get-Content .hallmonitor\\events.jsonl | Select-String stop"):
        assert not step.touches_protected(c), c
    assert not step.names_protected("cat app/auth.py") and not step.names_protected("git log .github")


# ---------------------------------------------------------------- tools that never reached the hook

def test_the_new_tools_are_classified_and_hooked():
    assert "office_edit" in P.EDIT_TOOLS
    assert {"start_subtask", "new_task", "spawn_subagent"} <= P.SPAWN_TOOLS
    for tool in ("office_edit", "start_subtask", "new_task", "create_html_artifact", "use_mcp_tool"):
        assert tool in install.TOOLS, tool


def test_office_edit_is_an_edit_so_the_protected_folders_are_off_limits(store):
    code, _, err = step.pre_tool({"tool": "office_edit", "input": {"path": ".bob/ledger.xlsx"}}, store)
    assert code == 2 and "can't be edited" in err


def test_other_tools_are_logged_and_kept_out_of_the_protected_folders(store):
    ok = step.pre_tool({"tool": "create_html_artifact", "input": {"title": "Hall Pass", "html": "<p>hi</p>"}}, store)
    assert ok == (0, "", "")
    assert Store_events(store)[-1]["action"] == "allow" and "not judged" in Store_events(store)[-1]["note"]
    for tool, inp in (("create_html_artifact", {"path": ".hallmonitor/hall-pass.html", "html": "x"}),
                      ("use_mcp_tool", {"server": "files", "arguments": {"path": ".bob/mcp.json", "content": "{}"}}),
                      ("use_mcp_tool", {"server": "files", "arguments": {"path": "C:\\\\repo\\\\.bob\\\\mcp.json"}})):
        code, _, err = step.pre_tool({"tool": tool, "input": inp}, store)
        assert code == 2 and "no tool may use them" in err, (tool, inp)


def test_hall_monitors_own_tools_are_never_judged(store):
    for tool in ("declare_intent", "mcp__hall-monitor__submit_claims"):
        assert step.pre_tool({"tool": tool, "input": {"files": [".bob/x"]}}, store) == (0, "", "")


def Store_events(store):
    from hallmonitor.store import Store
    return Store(store.root).events()


# ---------------------------------------------------------------- Receipts and the project's rules

def test_the_rules_are_checked_when_the_diff_changed_but_no_edit_receipt_exists(store, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev())
    store.add_decision("Every change ships with a test.", "user", kind="obligation")
    result = receipts.verify(store, [{"claim": "Refactored login.", "evidence": []}])
    assert not any("project rule" in r["claim"] for r in result["rows"])  # nothing changed: nothing to check
    # a shell command wrote the file: no edit receipt, but the diff has it
    (store.root / "app/service.py").write_text("def login():\n    return 'changed'\n", encoding="utf-8")
    assert not any(r.get("kind") == "edit" for r in store.evidence())
    result = receipts.verify(store, [{"claim": "Refactored login.", "evidence": []}])
    assert any("project rule" in r["claim"] for r in result["rows"])
