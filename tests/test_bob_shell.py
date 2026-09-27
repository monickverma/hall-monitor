"""Bob Shell on a fresh machine (Linux container, Bob Shell 2.0.5, Sept 27): `bob run` stops at IBM's
license, and says so only on stderr. No test ever starts Bob: subprocess.run is a fake."""
import subprocess
import sys
from pathlib import Path

from hallmonitor import bob

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import headless  # noqa: E402

REAL_RUN = bob._run  # conftest replaces bob._run for every test; these run it against a fake subprocess.run

LICENSE = ("Error: A license agreement is required. Please accept the license terms before proceeding.\n"
           "Launch Bob Shell in interactive mode or\nview license with `bob --show-license` and accept with "
           "`--accept-license`.")


def fake_bob(monkeypatch, stdout="", stderr="", code=0):
    calls = []
    monkeypatch.delenv("HM_DISABLE_BOB_SHELL", raising=False)
    monkeypatch.setattr(bob.shutil, "which", lambda name: "/usr/bin/bob")
    def run(cmd, **kw):
        assert kw.get("stdin") is subprocess.DEVNULL  # an open stdin once hung Bob Shell before it started
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, code, stdout=stdout, stderr=stderr)
    monkeypatch.setattr(bob.subprocess, "run", run)
    return calls


def test_the_license_and_team_id_are_opt_ins(tmp_path, monkeypatch):
    calls = fake_bob(monkeypatch, stdout='{"status": "success", "stats": {}}')
    monkeypatch.delenv("HM_BOB_ACCEPT_LICENSE", raising=False)
    monkeypatch.delenv("HM_BOB_TEAM_ID", raising=False)
    REAL_RUN(tmp_path, "supervised", "do the task", "1", "5", 60)
    assert "--accept-license" not in calls[-1] and "--team-id" not in calls[-1]
    monkeypatch.setenv("HM_BOB_ACCEPT_LICENSE", "1")
    monkeypatch.setenv("HM_BOB_TEAM_ID", "team-7")
    data = REAL_RUN(tmp_path, "supervised", "do the task", "1", "5", 60)
    cmd = calls[-1]
    assert "--accept-license" in cmd and cmd[cmd.index("--team-id") + 1] == "team-7"
    assert cmd[-1] == "do the task" and data["status"] == "success"


def test_a_failure_before_the_task_says_what_to_do(tmp_path, monkeypatch):
    fake_bob(monkeypatch, stderr=LICENSE, code=1)
    data = REAL_RUN(tmp_path, "supervised", "do the task", "1", "5", 60)
    assert data["status"] == "unparsed" and "license agreement is required" in data["error"]
    assert "HM_BOB_ACCEPT_LICENSE=1" in headless.bob_failure(data)
    key = {"status": "unparsed", "exit_code": 1,
           "error": "Error: Bob API key is required. Set BOB_API_KEY environment variable."}
    assert "BOB_API_KEY" in headless.bob_failure(key)
    assert headless.bob_failure({"status": "success", "exit_code": 0}) is None


def test_an_unexpanded_key_reference_counts_as_no_key(monkeypatch):
    """Bob leaves "${env:TYPESAFE_API_KEY}" literal when the variable is unset; that is no key, and on
    Windows the registry fallback must still get its turn."""
    from hallmonitor import jev
    monkeypatch.setenv("TYPESAFE_API_KEY", "${env:TYPESAFE_API_KEY}")
    monkeypatch.setattr(jev.os, "name", "posix")
    jev.load_key_from_user_env()
    assert "TYPESAFE_API_KEY" not in jev.os.environ


def test_a_result_after_an_error_line_is_still_read(tmp_path, monkeypatch):
    """Real Bob Shell 2.0.5: at the cost cap, `--format json` prints an error line, then the result."""
    out = ('{"type":"error","severity":"error","message":"The task reached the cost limit of 0.300 (spent: 0.302)."}\n'
           '{"type":"result","status":"success","stats":{"session_costs":0.302264,"tool_calls":11},'
           '"last_message":"Receipts: all 1 claims verified."}\n')
    fake_bob(monkeypatch, stdout=out)
    data = REAL_RUN(tmp_path, "supervised", "do the task", "0.30", "15", 60)
    assert data["status"] == "success" and data["stats"]["session_costs"] == 0.302264
    assert "cost limit" in data["error"] and data["last_message"].startswith("Receipts")
