"""Hook payloads the way real Bob sends them (probe, Sept 27): both payload shapes, Bob's real tool-input
keys, and absolute Windows paths from the edit tools. Jev is a fake throughout."""
import pytest

from conftest import FakeJev, make_repo, never
from hallmonitor import hook, jev, receipts
from hallmonitor.store import Store

SERVICE = "def login(user, password):\n    return 'ok'\n"


def docs_shape(event, tool=None, inp=None, **extra):
    """The shape in IBM's docs: {event, tool, input}."""
    return {"event": event, **({"tool": tool, "input": inp} if tool else {}), **extra}


def runtime_shape(event, tool=None, inp=None, **extra):
    """The shape Bob sends at runtime: {hook_event_name, tool_name, tool_input}."""
    return {"hook_event_name": event, **({"tool_name": tool, "tool_input": inp} if tool else {}), **extra}


SHAPES = pytest.mark.parametrize("shape", [docs_shape, runtime_shape], ids=["docs-shape", "runtime-shape"])


def win(path):
    """An absolute path as Bob's edit tools send it on Windows, with backslashes."""
    return str(path).replace("/", "\\")


@pytest.fixture
def repo(tmp_path):
    make_repo(tmp_path, {"app/service.py": SERVICE, "app/auth.py": "def check():\n    return False\n"},
              config={"test_command": "python -m pytest -q"})
    return tmp_path


def approve(store, files=(), commands=(), agent="main"):
    store.add_intent({"agent": agent, "intent": "add a docstring to login()", "files": list(files),
                      "commands": list(commands), "verdict": "approved", "why": ""})


@SHAPES
def test_write_file_with_an_absolute_path_runs_under_its_declared_intent(repo, shape, monkeypatch):
    store = Store(repo)
    approve(store, files=["app/service.py"])
    fake = FakeJev()
    monkeypatch.setattr(jev, "ask", fake)
    inp = {"path": win(repo / "app" / "service.py"), "content": "def login(user, password):\n    '''Log in.'''\n",
           "line_count": 2}
    code, _, err = hook.handle(shape("PreToolUse", "write_file", inp, cwd=str(repo)))
    assert code == 0, err
    asked = fake.calls[-1]
    assert "matches_intent" in asked["questions"] and asked["state"]["action"]["target"] == "app/service.py"
    assert "'''Log in.'''" in asked["state"]["action"]["content"]
    hook.handle(shape("PostToolUse", "write_file", inp, cwd=str(repo)))
    row = store.evidence()[-1]
    assert (row["kind"], row["file"], row["tool"], row["edit_seq"]) == ("edit", "app/service.py", "write_file", 1)



@SHAPES
def test_a_long_edit_reaches_jev_whole_or_marked_as_cut(repo, shape, monkeypatch):
    """Real Bob, Sept 27: an edit adding three methods was cut to its first 1,200 characters for the match
    question, so Jev judged it a mismatch with its intent, and the block revoked the intent."""
    store = Store(repo)
    approve(store, files=["app/service.py"])
    fake = FakeJev()
    monkeypatch.setattr(jev, "ask", fake)
    body = "".join(f"def helper_{i}():\n    '''Helper {i}.'''\n    return {i}\n\n" for i in range(60))
    inp = {"path": win(repo / "app" / "service.py"), "line": 3, "content": body}
    code, _, err = hook.handle(shape("PreToolUse", "insert_content", inp, cwd=str(repo)))
    assert code == 0, err
    assert len(body) > 2500 and "helper_59" in fake.calls[-1]["state"]["action"]["content"]
    inp["content"] = body * 4
    hook.handle(shape("PreToolUse", "insert_content", inp, cwd=str(repo)))
    shown = fake.calls[-1]["state"]["action"]["content"]
    assert shown.endswith("more characters not shown]") and len(shown) < 6100


@SHAPES
def test_search_and_replace_on_an_undeclared_file_is_blocked_and_explained(repo, shape, monkeypatch):
    monkeypatch.setattr(jev, "ask", never)
    inp = {"path": win(repo / "app" / "auth.py"), "search": "return False", "replace": "return True"}
    code, _, err = hook.handle(shape("PreToolUse", "search_and_replace", inp, cwd=str(repo)))
    assert code == 2 and "declare your intent first" in err and "app/auth.py" in err
    store = Store(repo)
    block = store.session()["blocks"][-1]
    assert (block["tool"], block["target"]) == ("search_and_replace", "app/auth.py")  # named repo-relative
    assert any(n.startswith("Blocked search_and_replace on app/auth.py:") for n in store.session()["notes"])


@SHAPES
def test_edits_into_the_supervisor_are_blocked_before_jev(repo, shape, monkeypatch):
    monkeypatch.setattr(jev, "ask", never)
    for tool, inp in (("write_file", {"path": win(repo / ".hallmonitor" / "config.json"), "content": "{}",
                                      "line_count": 1}),
                      ("insert_content", {"path": win(repo / ".bob" / "settings.json"), "line": 1, "content": "{"}),
                      ("search_and_replace", {"path": "../.hallmonitor/session.json", "search": "a", "replace": "b"})):
        code, _, err = hook.handle(shape("PreToolUse", tool, inp, cwd=str(repo / "app")))
        assert code == 2 and "can't be edited" in err, tool


@SHAPES
def test_insert_content_from_a_subfolder_is_matched_repo_relative(repo, shape, monkeypatch):
    store = Store(repo)
    approve(store, files=["app/service.py"])
    fake = FakeJev()
    monkeypatch.setattr(jev, "ask", fake)
    inp = {"path": "service.py", "line": 2, "content": "    # rate limit check goes here\n"}
    code, _, err = hook.handle(shape("PreToolUse", "insert_content", inp, cwd=str(repo / "app")))
    assert code == 0, err
    assert fake.calls[-1]["state"]["action"]["content"] == inp["content"]
    hook.handle(shape("PostToolUse", "insert_content", inp, cwd=str(repo / "app")))
    assert store.evidence()[-1]["file"] == "app/service.py"


@SHAPES
def test_execute_command_output_without_an_exit_code_becomes_a_receipt(repo, shape, monkeypatch):
    monkeypatch.setattr(jev, "ask", never)  # the test command is a safe command: allowed by code
    inp = {"command": "python -m pytest -q"}
    code, _, _ = hook.handle(shape("PreToolUse", "execute_command", inp, cwd=str(repo)))
    assert code == 0
    hook.handle(shape("PostToolUse", "execute_command", inp, cwd=str(repo), tool_response="3 passed in 0.02s"))
    rows = Store(repo).evidence()
    assert [(r["kind"], r.get("status"), r.get("status_source")) for r in rows] == \
        [("test", "pass", "inferred"), ("checkpoint", None, None)]
    hook.handle(shape("PostToolUse", "execute_command", inp, cwd=str(repo), tool_response="1 failed, 2 passed"))
    s = Store(repo).session()
    assert Store(repo).evidence()[-1]["status"] == "fail" and s["failed_step"]["command"] == "python -m pytest -q"


@SHAPES
def test_spawn_subagent_name_is_the_preset_so_subagents_are_numbered(repo, shape, monkeypatch):
    fake = FakeJev()
    monkeypatch.setattr(jev, "ask", fake)
    for n in (1, 2):
        inp = {"name": "explore", "description": f"Read app/service.py and report where login() starts ({n})."}
        code, _, err = hook.handle(shape("PreToolUse", "spawn_subagent", inp, cwd=str(repo)))
        assert code == 0, err
    spawned = [it for it in Store(repo).session()["intents"] if it.get("source") == "spawn"]
    assert [it["agent"] for it in spawned] == ["explore-subagent-1", "explore-subagent-2"]
    assert all(it["subagent_type"] == "explore" for it in spawned)
    hook.handle(shape("PostToolUse", "spawn_subagent", inp, cwd=str(repo), tool_response="login() starts at line 1."))
    ret = [e for e in Store(repo).events() if e["stage"] == "subagent_return"][-1]
    assert ret["action"] == "accept" and ret["agent"] == "explore"


@SHAPES
def test_stop_judges_the_last_assistant_message_only_for_uncovered_edits(repo, shape, monkeypatch):
    judged = []
    monkeypatch.setattr(receipts, "verify", lambda s, text, **k: judged.append(text) or {"status": "accept"})
    code, _, _ = hook.handle(shape("Stop", cwd=str(repo), last_assistant_message="Nothing to do."))
    assert code == 0 and judged == []  # no edits this turn
    s = Store(repo).session()
    s["edit_seq"] = 1
    Store(repo).save_session(s)
    hook.handle(shape("Stop", cwd=str(repo), last_assistant_message="Done: added the docstring."))
    assert judged == ["Done: added the docstring."]
    assert (repo / ".hallmonitor" / "hall-pass.html").exists()


@SHAPES
def test_session_start_and_user_prompt_briefings(repo, shape, monkeypatch):
    monkeypatch.setattr(jev, "ask", never)  # no AGENTS.md decisions to import
    code, out, _ = hook.handle(shape("SessionStart", cwd=str(repo), session_id="s1"))
    assert code == 0 and out.startswith("[Hall Monitor]") and "declare_intent" in out
    fake = FakeJev()
    monkeypatch.setattr(jev, "ask", fake)
    code, out, _ = hook.handle(shape("UserPromptSubmit", cwd=str(repo), prompt="Add a docstring to login()."))
    assert code == 0 and "Goal: Add a docstring to login()." in out
    assert Store(repo).session()["goal"] == "Add a docstring to login()."


@SHAPES
def test_an_unknown_event_is_ignored(repo, shape):
    assert hook.handle(shape("Notification", cwd=str(repo))) == (0, "", "")


def test_a_crash_is_logged_and_fails_open_by_default(repo, monkeypatch):
    def boom(p, s):
        raise KeyError("tool_input")
    monkeypatch.setitem(hook.HANDLERS, "PreToolUse", boom)
    assert hook.handle(runtime_shape("PreToolUse", "write_file", {"path": "x.py"}, cwd=str(repo))) == (0, "", "")
    err = [e for e in Store(repo).events() if e["stage"] == "error"][-1]
    assert "KeyError" in err["error"] and err["trace"]
    (repo / ".hallmonitor" / "config.json").write_text('{"fail_open": false}')
    code, _, msg = hook.handle(runtime_shape("PreToolUse", "write_file", {"path": "x.py"}, cwd=str(repo)))
    assert code == 2 and "fail_open is off" in msg
