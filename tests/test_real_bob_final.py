"""Final real Bob Shell run, Sept 27: the task with two parallel subagents ended STUCK although the main
agent's claims verified. A tidy-up subagent's three submissions were held to every project rule and used up
the task's send-backs, and "tests must fail without the change" went to Jev although fail-before answers it."""
import sys

from conftest import FakeJev, make_repo
from hallmonitor import evidence as EV, jev, receipts
from hallmonitor.store import Store

CMD = f'"{sys.executable}" -m pytest -q -p no:cacheprovider'
RULE = "Every behavior change must ship with a test that fails without the change."


def repo(tmp_path):
    store = make_repo(tmp_path, {"app/__init__.py": "", "app/rl.py": "def limit():\n    return 0\n",
                                 "tests/__init__.py": ""},
                      config={"test_command": CMD, "max_mutants": 0, "max_extreme_mutants": 0})
    store.add_decision(RULE, "docs/security-policy.pdf §4", kind="obligation")
    return store


def change(store, test_body):
    for path, text in (("app/rl.py", "def limit():\n    return 5\n"), ("tests/test_rl.py", test_body)):
        (store.root / path).write_text(text, encoding="utf-8")
        EV.record({"tool": "write_file", "input": {"path": path, "content": text}}, store)


def test_a_subagents_submission_is_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev(verdict=("says_nothing", 0.9)))
    store = repo(tmp_path)
    change(store, "from app.rl import limit\n\ndef test_limit():\n    assert limit() == 5\n")
    for _ in range(3):
        r = receipts.verify(store, [{"claim": "Tidied app/rl.py.", "evidence": ["E1"]}], agent="tidy-subagent")
        assert not any("D1" in row["claim"] for row in r["rows"])  # the task's rules wait for the main agent
    s = Store(store.root).session()
    assert s["send_backs"] == 0 and s["agent_send_backs"]["tidy-subagent"] >= 2


def test_the_fails_without_the_change_rule_is_decided_by_fail_before(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev())
    store = repo(tmp_path)
    change(store, "from app.rl import limit\n\ndef test_limit():\n    assert limit() == 5\n")
    rows = receipts.verify(store, [{"claim": "Raised the limit in app/rl.py.", "evidence": ["E1"]}])["rows"]
    rule = next(r for r in rows if "D1" in r["claim"])
    assert (rule["state"], rule["code"], rule["tier"]) == ("verified", "fail_before", "code")


def test_a_test_that_passes_without_the_change_breaks_that_rule(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev())
    store = repo(tmp_path)
    change(store, "from app.rl import limit\n\ndef test_limit():\n    assert limit() is not None\n")
    rows = receipts.verify(store, [{"claim": "Raised the limit in app/rl.py.", "evidence": ["E1"]}])["rows"]
    assert next(r for r in rows if "D1" in r["claim"])["state"] == "contradicted"


def test_a_subagents_verified_part_doesnt_make_the_task_verified(tmp_path, monkeypatch):
    """Confirming real Bob run: subagent-B's docstring claims verified, the main agent never submitted, and the
    Hall Pass and the CI gate read the task as VERIFIED."""
    from hallmonitor import report
    monkeypatch.setattr(jev, "ask", FakeJev())
    store = repo(tmp_path)
    change(store, "from app.rl import limit\n\ndef test_limit():\n    assert limit() == 5\n")
    receipts.verify(store, [{"claim": "Added a docstring to app/rl.py.", "evidence": ["E1"]}], agent="subagent-B")
    assert [e["agent"] for e in store.events() if e["stage"] == "receipts"] == ["subagent-B"]
    assert receipts.task_rounds(store.events()) == []
    _, summary = report.write_hall_pass(store)
    assert "receipts: IN PROGRESS" in summary
    receipts.verify(store, [{"claim": "Raised the limit in app/rl.py.", "evidence": ["E1"]}])
    assert [e["agent"] for e in receipts.task_rounds(store.events())] == ["main"]


def test_an_edit_is_matched_to_the_parallel_agent_whose_intent_it_fits(tmp_path, monkeypatch):
    """Confirming real run: subagent-A's limiter edit to app/service.py was checked against subagent-B's newer
    docstring intent for the same file, blocked as a mismatch, and B's intent revoked."""
    from hallmonitor import hook
    fits = lambda qid, state: 0.1 if "docstring" in (state.get("stated_reason") or "") else 0.95  # noqa: E731
    monkeypatch.setattr(jev, "ask", FakeJev(matches_intent=fits))
    store = repo(tmp_path)
    service = store.root / "app" / "service.py"
    service.write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    for agent, intent in (("subagent-A", "Wire the rate limiter into login() in app/service.py"),
                          ("subagent-B", "Improve the module docstring in app/service.py")):
        store.add_intent({"agent": agent, "intent": intent, "files": ["app/service.py"], "commands": [],
                          "verdict": "approved", "why": ""})
    edit = {"event": "PreToolUse", "tool": "write_file", "cwd": str(store.root),
            "input": {"path": "app/service.py", "content": "from app.rl import limit\n\ndef login():\n    limit()\n"}}
    code, _, err = hook.handle(edit)
    assert code == 0, err
    step_event = [e for e in store.events() if e["stage"] == "step"][-1]
    assert step_event["action"] == "allow" and step_event["intent"] == "I1"  # subagent-A's intent
    assert all(it["verdict"] == "approved" for it in Store(store.root).session()["intents"])  # nothing revoked


PASSWORD_RULE = "Password comparison must use a constant-time algorithm (do not use == or != for password comparison)."


def test_a_rule_about_code_the_change_doesnt_touch_doesnt_apply(tmp_path, monkeypatch):
    """Real Bob run 10 ($1.50, subagents): rule D2 came back "needs evidence" on a rate-limit change with no
    password code, and Bob spent the rest of its cost cap answering it. A rule about every change still applies."""
    monkeypatch.setattr(jev, "ask", FakeJev())
    store = repo(tmp_path)
    store.add_decision(PASSWORD_RULE, "docs/security-policy.pdf §2", kind="obligation")
    change(store, "from app.rl import limit\n\ndef test_limit():\n    assert limit() == 5  # not a password\n")
    rows = receipts.verify(store, [{"claim": "Raised the limit in app/rl.py.", "evidence": ["E1"]}])["rows"]
    d2 = next(r for r in rows if "D2" in r["claim"])
    assert (d2["state"], d2["code"], d2["tier"]) == ("verified", "not_applicable", "code")
    assert next(r for r in rows if "D1" in r["claim"])["code"] == "fail_before"  # every change: still checked
    for rule in (RULE, "Tests must assert on the specific changed behavior.", "Do not add dependencies.",
                 "The finished work must include a changelog entry."):
        assert receipts.untouched_subject(rule, {}) is None, rule


def test_a_rule_about_code_the_change_touches_is_judged(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev())
    store = repo(tmp_path)
    store.add_decision(PASSWORD_RULE, "docs/security-policy.pdf §2", kind="obligation")
    changed = {"app/auth.py": {"status": "modified", "added": [(9, "    return expected == given")],
                               "removed": 1, "removed_lines": ["    return hmac.compare_digest(expected, given)"]}}
    assert receipts.not_applicable(PASSWORD_RULE, [], changed) is None  # a removed line counts too
    change(store, "from app.rl import limit\n\ndef test_limit():\n    assert limit() == 5\n")
    (store.root / "app/rl.py").write_text("def limit(password=''):\n    return 5 if password != 'x' else 0\n",
                                          encoding="utf-8")
    EV.record({"tool": "write_file", "input": {"path": "app/rl.py", "content": "..."}}, store)
    rows = receipts.verify(store, [{"claim": "Raised the limit in app/rl.py.", "evidence": ["E1"]}])["rows"]
    assert next(r for r in rows if "D2" in r["claim"])["tier"] != "code"  # it applies now: judged on evidence


def test_a_line_that_mentions_passwords_but_compares_nothing_doesnt_apply_the_rule():
    """Real Bob re-run, Sept 27 (subagents, $2.03): D2 came back "needs evidence" three rounds running. Bob's edit to
    login(user, password) touched lines that mention `password`, and its tests compare login()'s results with ==."""
    changed = {"app/service.py": {"status": "modified", "removed": 2, "added": [
        (1, "from app.ratelimit import check_rate_limit"), (4, "def login(user: str, password: str) -> str:"),
        (5, "    if not check_rate_limit(user):"), (6, '        return "rate_limited"'),
        (7, "    if not check_password(user, password):")],
        "removed_lines": ["def login(user: str, password: str) -> str:", "    if not check_password(user, password):"]},
        "tests/test_service.py": {"status": "modified", "removed": 0, "removed_lines": [],
                                  "added": [(12, '    assert login("alice", "wrong password") == "denied"')]},
        "app/ratelimit.py": {"status": "new", "removed": 0, "removed_lines": [],
                             "added": [(9, "    if len(q) >= 5:"), (10, "        return False")]}}
    assert receipts.untouched_subject(PASSWORD_RULE, changed) == "Password comparison"
    assert receipts.not_applicable(PASSWORD_RULE, [], changed)[1] == "not_applicable"
    for rule in (RULE, "Tests must assert on the specific changed behavior; tests that only exercise the happy path "
                       "or unrelated behavior do not satisfy the testing requirement."):  # D4 and D5 always apply
        assert receipts.untouched_subject(rule, changed) is None, rule


def test_a_new_comparison_in_password_code_applies_the_rule(tmp_path):
    """The comparison names no password, but the file it's in is about passwords."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "auth.py").write_text(
        "def check_password(user, password):\n    given = digest(password)\n    if given != expected(user):\n"
        "        return False\n    return True\n", encoding="utf-8")
    changed = {"app/auth.py": {"status": "modified", "removed": 0, "removed_lines": [],
                               "added": [(3, "    if given != expected(user):"), (4, "        return False")]}}
    assert receipts.untouched_subject(PASSWORD_RULE, changed) == "Password comparison"  # the lines alone don't say
    assert receipts.untouched_subject(PASSWORD_RULE, changed, tmp_path) is None
    ratelimit = {"app/ratelimit.py": {"status": "new", "removed": 0, "removed_lines": [],
                                      "added": [(1, "def allow(user):"), (2, "    return len(seen[user]) != 5")]}}
    assert receipts.untouched_subject(PASSWORD_RULE, ratelimit, tmp_path) == "Password comparison"


def test_a_rule_that_needs_evidence_twice_on_the_same_diff_goes_to_the_user(tmp_path, monkeypatch):
    """Real Bob re-run, Sept 27 (subagents, $2.03): D2 came back "needs evidence" in three rounds, the last two on
    the same diff, and the task ended STUCK. Resubmitting can't settle it, so the second time it's a question for the
    user and doesn't use up a send-back. A changed diff is a new attempt."""
    from hallmonitor import report
    unsure = lambda qid, state: ("says_nothing", 0.9) if "D2" in state["claim"] else ("supports", 0.97)  # noqa: E731
    monkeypatch.setattr(jev, "ask", FakeJev(verdict=unsure))
    store = repo(tmp_path)
    store.add_decision(PASSWORD_RULE, "docs/security-policy.pdf §2", kind="obligation")
    change(store, "from app.rl import limit\n\ndef test_limit():\n    assert limit() == 5\n")
    (store.root / "app/rl.py").write_text("def limit(password=''):\n    return 5 if password != 'x' else 0\n",
                                          encoding="utf-8")
    EV.record({"tool": "write_file", "input": {"path": "app/rl.py", "content": "..."}}, store)
    claims = [{"claim": "Raised the limit in app/rl.py.", "evidence": ["E1"]}]

    def d2(result):
        return next(r for r in result["rows"] if "D2" in r["claim"])
    first = receipts.verify(store, claims)
    assert (first["status"], first["send_backs"], d2(first)["state"]) == ("send_back", 1, "needs_evidence")
    for _ in range(2):  # the same diff: asked, not sent back
        again = receipts.verify(store, claims)
        assert (again["status"], again["send_backs"]) == ("audit", 1)
        assert (d2(again)["state"], d2(again)["code"]) == ("cant_check", "ask_user")
        assert "Ask the user whether the finished work satisfies it." in receipts.message(again)
        assert "need the user's answer" in receipts.message(again)
    assert "receipts: ASKS YOU" in report.write_hall_pass(store)[1]
    (store.root / "app/rl.py").write_text("def limit(password=''):\n    return 5 if password != 'y' else 0\n",
                                          encoding="utf-8")
    EV.record({"tool": "write_file", "input": {"path": "app/rl.py", "content": "..."}}, store)
    changed = receipts.verify(store, claims)
    assert (changed["status"], changed["send_backs"], d2(changed)["state"]) == ("send_back", 2, "needs_evidence")
