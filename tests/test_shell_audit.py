"""The Receipts auditor's own `bob run` (bob.shell_audit), turned on after real Bob, Sept 27: it had never run,
because Bob starts the MCP server without BOB_API_KEY. No test starts Bob: subprocess.run is a fake."""
import json
import subprocess
import threading
import time
from pathlib import Path

from conftest import FakeJev, make_repo
from hallmonitor import bob, evidence as EV, jev, receipts
from test_bob_shell import REAL_RUN  # at import: before conftest stubs bob._run

GIT_RUN = subprocess.run
RESULT = json.dumps({"status": "success", "last_message": "VERDICT: holds. app/rl.py:2 returns 5.",
                     "stats": {"session_costs": 0.05}})


def repo(tmp_path):
    store = make_repo(tmp_path, {"app/__init__.py": "", "app/rl.py": "def limit():\n    return 0\n"},
                      config={"test_command": "python -c \"print('1 passed')\"", "max_mutants": 0,
                              "max_extreme_mutants": 0})
    (store.root / "app/rl.py").write_text("def limit():\n    return 5\n", encoding="utf-8")
    EV.record({"tool": "write_file", "input": {"path": "app/rl.py", "content": "return 5"}}, store)
    return store


def fake_bob(monkeypatch, answer):
    """Bob Shell answers with `answer(cmd)`; git and everything else run for real."""
    monkeypatch.setattr(bob, "_run", REAL_RUN)
    monkeypatch.delenv("HM_DISABLE_BOB_SHELL", raising=False)
    monkeypatch.setattr(bob.shutil, "which", lambda name: "/usr/bin/bob")

    def run(cmd, **kw):
        if cmd[0] != "/usr/bin/bob":
            return GIT_RUN(cmd, **kw)
        return answer(cmd)
    monkeypatch.setattr(bob.subprocess, "run", run)


def test_the_auditor_works_in_a_copy_without_hall_monitors_hooks_or_server(tmp_path, monkeypatch):
    store = repo(tmp_path)
    (store.root / ".bob").mkdir()
    for name in ("settings.json", "mcp.json", "custom_modes.yaml"):
        (store.root / ".bob" / name).write_text("{}", encoding="utf-8")
    seen = {}

    def answer(cmd):
        ws = Path(cmd[cmd.index("--workspace") + 1])
        seen.update(ws=ws, bob=sorted(p.name for p in (ws / ".bob").iterdir()), code=(ws / "app/rl.py").read_text())
        return subprocess.CompletedProcess(cmd, 0, stdout=RESULT, stderr="")
    fake_bob(monkeypatch, answer)
    assert bob.shell_audit(store.root, "Audit this claim independently: ...").startswith("VERDICT: holds")
    assert seen["ws"] != store.root and seen["bob"] == ["custom_modes.yaml"] and "return 5" in seen["code"]
    logged = [json.loads(x) for x in (store.dir / "bob_runs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert logged[-1]["mode"] == "hm-auditor" and logged[-1]["stats"]["session_costs"] == 0.05


def test_an_audit_that_runs_out_of_time_is_logged_and_isnt_an_audit(tmp_path, monkeypatch):
    store = repo(tmp_path)

    def answer(cmd):
        raise subprocess.TimeoutExpired(cmd, 40)
    fake_bob(monkeypatch, answer)
    assert bob.shell_audit(store.root, "Audit this claim independently: ...", timeout=40) is None
    logged = json.loads((store.dir / "bob_runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert logged["status"] == "timeout" and "40s" in logged["error"]


def test_an_audit_that_failed_before_it_ran_isnt_an_audit(tmp_path, monkeypatch):
    """Real Bob, Sept 27: every audit ended in about 2 s with "Bob API key is required", and nothing said why."""
    store = repo(tmp_path)
    monkeypatch.setenv("BOB_API_KEY", "bob-key-value-123")
    fake_bob(monkeypatch, lambda cmd: subprocess.CompletedProcess(
        cmd, 1, stdout="Usage: bob run ...", stderr="Error: bad key bob-key-value-123"))
    assert bob.shell_audit(store.root, "Audit this claim independently: ...") is None
    logged = (store.dir / "bob_runs.jsonl").read_text(encoding="utf-8")
    assert "bad key <BOB_API_KEY>" in logged and "bob-key-value-123" not in logged


def test_a_rounds_audits_run_at_once_within_the_time_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev(verdict=("supports", 0.7), false=0.2))  # uncertain: worth an audit
    store = repo(tmp_path)
    running, peak, budgets, lock = [0], [0], [], threading.Lock()

    def audit(root, brief, timeout):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
            budgets.append(timeout)
        time.sleep(0.5)
        with lock:
            running[0] -= 1
        return "VERDICT: holds. app/rl.py:2 returns 5."
    monkeypatch.setattr(bob, "shell_audit", audit)
    claims = [{"claim": "Raised the limit in app/rl.py to 5.", "evidence": ["E1"]},
              {"claim": "limit() in app/rl.py now returns 5.", "evidence": ["E1"]}]
    rows = receipts.verify(store, claims)["rows"]
    assert [r["tier"] for r in rows] == ["bob_shell_audit", "bob_shell_audit"]
    assert peak[0] == 2 and budgets == [40, 40]


def test_the_mcp_server_gets_the_bob_key_by_reference(monkeypatch):
    monkeypatch.setenv("BOB_API_KEY", "${env:BOB_API_KEY}")  # Bob leaves it as is when BOB_API_KEY is unset
    monkeypatch.setattr(jev.os, "name", "posix")
    jev.load_key_from_user_env()
    assert "BOB_API_KEY" not in jev.os.environ
