"""Real Bob IDE 2.2.1, Oct 15 (bob_sessions/events/2026-10-15_ide-run_member1_events.jsonl): the five things the run
exposed. Jev is a fake and no test starts Bob Shell."""
import json
import threading
import time
from pathlib import Path

from conftest import FakeJev, make_repo
from hallmonitor import bob, brief, evidence as EV, gitutil, hook, jev, mcp_server, receipts, review, step

ROOT = Path(__file__).resolve().parents[1]
PASSING = "python -c \"print('1 passed')\""
SERVICE = "def login(user, password):\n    return check(user, password)\n"
RATELIMIT = "def is_allowed(user):\n    return True\n"


def write(store, path, text):
    (store.root / path).parent.mkdir(parents=True, exist_ok=True)
    (store.root / path).write_text(text, encoding="utf-8")
    EV.record({"tool": "write_file", "input": {"path": path, "content": text}}, store)


# ---------------------------------------------------------------- 1. a Receipts round answers within Bob's 60 s

def audit_repo(tmp_path):
    store = make_repo(tmp_path, {"app/__init__.py": "", "app/rl.py": "def limit():\n    return 0\n"},
                      config={"test_command": PASSING, "max_mutants": 0, "max_extreme_mutants": 0})
    write(store, "app/rl.py", "def limit():\n    return 5\n")
    return store


def test_a_round_answers_before_a_slow_audit_and_the_next_round_picks_it_up(tmp_path, monkeypatch):
    """Every audit round took 60-94 s, past Bob IDE's 60 s for a tool call: Bob saw "Error from Submit Claims",
    restarted the server, retried and never saw a verdict. Now the audit runs on, and the round answers in time."""
    monkeypatch.setattr(jev, "ask", FakeJev(verdict=("supports", 0.7), false=0.2))  # uncertain: worth an audit
    store = audit_repo(tmp_path)
    done = threading.Event()

    def slow_audit(root, brief_, timeout):
        done.wait(10)
        return "VERDICT: holds. app/rl.py:2 returns 5."
    monkeypatch.setattr(bob, "shell_audit", slow_audit)
    claims = [{"claim": "limit() in app/rl.py now returns 5.", "evidence": ["E1"]}]

    t0 = time.time()
    first = receipts.verify(store, claims, budget=2)
    assert time.time() - t0 < 5
    assert first["status"] == "audit" and first["rows"][0]["code"] == "audit_running"
    assert first["audits"] == [] and store.session()["send_backs"] == 0  # no explore subagent, no send-back
    text = receipts.message(first)
    assert "AUDIT RUNNING for claim 0" in text and "AUDIT NEEDED" not in text

    done.set()
    second = receipts.verify(store, claims, budget=2)
    assert second["status"] == "accept" and second["rows"][0]["tier"] == "bob_shell_audit"


def test_an_audit_that_fails_in_the_background_falls_back_to_the_explore_subagent(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev(verdict=("supports", 0.7), false=0.2))
    store = audit_repo(tmp_path)
    monkeypatch.setattr(bob, "shell_audit", lambda root, brief_, timeout: None)  # timed out, or no Bob Shell
    result = receipts.verify(store, [{"claim": "limit() in app/rl.py now returns 5.", "evidence": ["E1"]}], budget=30)
    assert result["status"] == "audit" and result["running_audits"] == []
    assert "AUDIT NEEDED for claim 0" in receipts.message(result)


def test_sabotage_starts_no_mutant_past_the_deadline(tmp_path):
    store = make_repo(tmp_path, {"app/__init__.py": "", "app/rl.py": "def limit():\n    return 0\n"})
    (store.root / "app/rl.py").write_text("def limit():\n    return 5 + 0\n", encoding="utf-8")
    changes = gitutil.changes(store.root, store.session()["base"])
    assert gitutil.plan_mutants(store.root, changes)
    sab = gitutil.sabotage(store.root, changes, PASSING, deadline=time.time() - 1)
    assert sab["mutants"] == 0 and "time budget used up" in sab["note"]


def test_submit_claims_runs_with_the_round_budget(tmp_path, monkeypatch):
    store = make_repo(tmp_path, {"app/__init__.py": ""})
    seen = {}

    def verify(store_, claims, audit_notes=None, agent="main", budget=None):
        seen["budget"] = budget
        return {"status": "accept"}
    monkeypatch.setattr(receipts, "verify", verify)
    monkeypatch.setattr(review, "after_verify", lambda s, r, notes=None: r)
    monkeypatch.setattr(review, "message", lambda r: "ok")
    assert mcp_server.call("submit_claims", {"claims": ["Did it."]}, store) == "ok"
    assert seen["budget"] == store.config()["round_budget"] == 45


# ---------------------------------------------------------------- 2. claims judged against the tree they started from

def rate_limit_repo(tmp_path):
    """The last task's rate-limit work, verified but never committed: app/service.py changed, app/ratelimit.py new."""
    store = make_repo(tmp_path, {"app/__init__.py": "", "app/service.py": "def login(user, password):\n    return 1\n"},
                      config={"test_command": PASSING, "max_mutants": 0, "max_extreme_mutants": 0})
    (store.root / "app/service.py").write_text(SERVICE, encoding="utf-8")
    (store.root / "app/ratelimit.py").write_text(RATELIMIT, encoding="utf-8")
    return store


def test_a_snapshot_base_leaves_the_last_tasks_uncommitted_work_out_of_the_diff(tmp_path):
    store = rate_limit_repo(tmp_path)
    head = gitutil.head(store.root)
    base = gitutil.snapshot(store.root, brief.TASK_BASE)
    assert base and base != head and gitutil.git(store.root, "rev-parse", brief.TASK_BASE).strip() == base
    assert gitutil.git(store.root, "rev-parse", "HEAD").strip() == head  # the branch and index are untouched
    assert gitutil.git(store.root, "status", "--porcelain").count("??") == 1
    assert gitutil.changes(store.root, base) == {}

    (store.root / "app/service.py").write_text('def login(user, password):\n    """Log in."""\n'
                                               "    return check(user, password)\n", encoding="utf-8")
    (store.root / "app/ratelimit.py").write_text('def is_allowed(user):\n    """Allow."""\n    return True\n',
                                                 encoding="utf-8")
    changes = gitutil.changes(store.root, base)
    assert {f: [t for _, t in c["added"]] for f, c in changes.items()} == \
        {"app/service.py": ['    """Log in."""'], "app/ratelimit.py": ['    """Allow."""']}
    assert all(c["status"] == "modified" for c in changes.values())
    assert gitutil.behavior_lines(store.root, base, changes) == []  # docstrings only
    assert gitutil.changes(store.root, head)["app/ratelimit.py"]["status"] == "new"  # against HEAD it's all new


def test_a_clean_tree_snapshots_to_head(tmp_path):
    store = make_repo(tmp_path, {"app/__init__.py": ""})
    assert gitutil.snapshot(store.root, brief.TASK_BASE) == gitutil.head(store.root)


def test_a_docstring_subagent_is_judged_on_its_own_docstrings(tmp_path, monkeypatch):
    """A subagent's "docstrings only, no behavior changes" came back CONTRADICTED three times, then STUCK: the diff
    against HEAD still held the last task's rate-limit work."""
    fake = FakeJev()
    monkeypatch.setattr(jev, "ask", fake)
    store = rate_limit_repo(tmp_path)
    s = store.session()
    s["edit_seq"] = s["verified_edit_seq"] = 3  # the rate-limit task ended VERIFIED
    store.save_session(s)
    hook.handle({"hook_event_name": "SessionStart", "cwd": str(store.root)})
    assert store.session()["base"] != gitutil.head(store.root)

    step.declare_intent(store, "Add a one-line docstring to login().", files=["app/service.py"],
                        agent="service-agent", agent_task="Docstrings in app/service.py only.")
    started = store.session()["agent_bases"]["service-agent"]
    assert gitutil.git(store.root, "rev-parse", "refs/hallmonitor/agent/service-agent").strip() == started
    write(store, "app/service.py", 'def login(user, password):\n    """Log in."""\n    return check(user, password)\n')

    fake.calls.clear()
    claim = "Added a one-line docstring to every function in app/service.py with no behavior changes."
    result = receipts.verify(store, [{"claim": claim, "evidence": ["E1"]}], agent="service-agent")
    diffs = [json.dumps(c["state"]) for c in fake.calls if "evidence" in c["state"]]
    assert diffs and all("Log in." in d and "check(user, password)" not in d.split("Log in.")[0] for d in diffs)
    assert all("is_allowed" not in d for d in diffs)
    assert result["rows"][0]["state"] == "verified"

    # The main agent's round is judged against the task's start: the same docstring, no rate-limit work
    main = receipts.verify(store, [{"claim": claim, "evidence": ["E1"]}])
    assert set(gitutil.changes(store.root, store.session()["base"])) == {"app/service.py"}
    assert all(r["state"] == "verified" for r in main["rows"])


def test_a_new_task_keeps_its_base_while_the_last_tasks_edits_are_unverified(tmp_path, monkeypatch):
    """Jev may read a follow-up as a new task; claims about edits no round verified must still see them."""
    monkeypatch.setattr(jev, "ask", FakeJev(new_task=0.97))
    store = rate_limit_repo(tmp_path)
    s = store.session()
    s.update(goal="Add a rate limit.", edit_seq=2, verified_edit_seq=0)
    store.save_session(s)
    before = s["base"]
    hook.handle({"hook_event_name": "UserPromptSubmit", "cwd": str(store.root), "prompt": "Now add docstrings."})
    assert store.session()["base"] == before

    s = store.session()
    s["verified_edit_seq"] = 2
    store.save_session(s)
    hook.handle({"hook_event_name": "UserPromptSubmit", "cwd": str(store.root), "prompt": "Now tidy the README."})
    assert store.session()["base"] not in (before, None)


# ---------------------------------------------------------------- 3. reads of .hallmonitor/ treated alike

READS = ("$html = Get-Content '.hallmonitor/hall-pass.html' -Raw; Write-Output $html",
         "Get-Content .hallmonitor\\hall-pass.html -Raw",
         "$e = Get-Content .hallmonitor/events.jsonl | Select-String stop; $e")


def test_reading_hall_monitors_records_through_a_variable_is_a_read(tmp_path):
    store = make_repo(tmp_path, {"app/__init__.py": ""})
    for command in READS:
        assert not step.touches_protected(command), command
        assert step.is_safe_command(store.config(), command), command
        code, _, err = step.pre_tool({"tool": "execute_command", "input": {"command": command}}, store)
        assert code == 0, (command, err)


def test_a_variable_doesnt_hide_a_write():
    for command in ("$x = Get-Content a.txt; Set-Content .hallmonitor/session.json $x",
                    "$x = Remove-Item .bob/mcp.json", "Write-Output $x > .bob/mcp.json",
                    "$x = Get-Content .bob/mcp.json; $x | Out-File app/x.py", "$(Remove-Item .bob); Get-Content .bob/x",
                    "$x = Get-Content .bob/mcp.json && rm .bob/x"):
        assert step.touches_protected(command), command


# ---------------------------------------------------------------- 4. /hall-pass without create_html_artifact

def test_hall_pass_gives_the_path_and_asks_for_no_shell_read(tmp_path):
    store = make_repo(tmp_path, {"app/__init__.py": ""})
    text = mcp_server.call("hall_pass", {}, store)
    assert str((store.dir / "hall-pass.html").resolve()) in text
    assert "don't read the file with a shell command" in text and "Only if you have a create_html_artifact" in text
    for doc in ("bob/commands/hall-pass.md", "bob/skills/hall-monitor-protocol/SKILL.md", "bob/custom_modes.yaml"):
        body = (ROOT / doc).read_text(encoding="utf-8")
        assert "Get-Content" not in body and "path" in body, doc
        assert "create_html_artifact" not in body or "only if" in body.lower(), doc


# ---------------------------------------------------------------- 5. a slash command doesn't become the goal

HALL_PASS_PROMPT = ("name: hall-pass\ndescription: Publish the Hall Pass for this session as a shareable one-page "
                    "summary\nmetadata:\n\nCall the hall-monitor hall_pass tool. Read that file with your read_file "
                    "tool and publish it with create_html_artifact.")
DECISIONS_PROMPT = ("name: decisions\ndescription: 'Turn a policy document, ADR or spec into rules Hall Monitor "
                    "enforces'\nmetadata:\n\nUse the extract-decisions skill on $1. Record every rule it contains with "
                    "the hall-monitor record_decision tool, then list the decisions now enforced.\n\n\n"
                    "docs/security-policy.pdf")


def test_a_slash_command_keeps_the_sessions_goal(tmp_path, monkeypatch):
    fake = FakeJev(new_task=0.97)  # Jev would call it a new task
    monkeypatch.setattr(jev, "ask", fake)
    store = make_repo(tmp_path, {"app/__init__.py": ""})
    s = store.session()
    s.update(goal="Add a per-user limit of 5 login attempts per minute.", send_backs=1)
    store.save_session(s)
    code, out, _ = hook.handle({"hook_event_name": "UserPromptSubmit", "cwd": str(store.root),
                                "prompt": HALL_PASS_PROMPT})
    s = store.session()
    assert code == 0 and s["goal"] == "Add a per-user limit of 5 login attempts per minute." and s["send_backs"] == 1
    assert "Goal: Add a per-user limit" in out
    assert fake.calls[0]["state"]["sentences"] == []  # the command's own wording isn't the user stating rules
    assert not store.ledger()


def test_a_first_slash_command_names_the_goal_by_the_command(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev())
    store = make_repo(tmp_path, {"app/__init__.py": ""})
    hook.handle({"hook_event_name": "UserPromptSubmit", "cwd": str(store.root), "prompt": DECISIONS_PROMPT})
    assert store.session()["goal"] == ("/decisions docs/security-policy.pdf (Turn a policy document, ADR or spec "
                                       "into rules Hall Monitor enforces)")


def test_what_counts_as_a_slash_command(tmp_path):
    from hallmonitor import payload as P
    (tmp_path / ".bob" / "commands").mkdir(parents=True)
    (tmp_path / ".bob" / "commands" / "receipts.md").write_text("---\ndescription: x\n---\nCall list_evidence.\n",
                                                                encoding="utf-8")
    assert P.slash_command("/receipts", tmp_path) == ("receipts", "", "")
    assert P.slash_command("/fix the login bug", tmp_path) is None  # no such command: a request
    assert P.slash_command("Add a limit, then run /receipts.", tmp_path) is None
    expanded = "name: receipts\ndescription: Check claims\nmetadata:\n\nCall list_evidence.\n\n\nonly app/"
    assert P.slash_command(expanded, tmp_path) == ("receipts", "Check claims", "only app/")
