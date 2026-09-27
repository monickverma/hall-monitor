"""The MCP server as Bob talks to it: JSON-RPC 2.0, one message per line over stdio. No Jev calls."""
import json
import os
import subprocess
import sys
from pathlib import Path

from hallmonitor import mcp_server
from hallmonitor.store import Store

ROOT = Path(__file__).resolve().parents[1]
SEVEN = {"declare_intent", "record_decision", "explain_block", "list_decisions", "list_evidence",
         "submit_claims", "hall_pass"}


def rpc(method, params=None, mid=1):
    return {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}


def call(name, args, root):
    return mcp_server.handle(rpc("tools/call", {"name": name, "arguments": args}), root)["result"]


def test_initialize_then_tools_list_gives_exactly_the_seven_tools(tmp_path):
    r = mcp_server.handle(rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}}), tmp_path)
    assert r["jsonrpc"] == "2.0" and r["id"] == 1
    assert r["result"]["protocolVersion"] == "2025-06-18"
    assert r["result"]["serverInfo"]["name"] == "hall-monitor" and "tools" in r["result"]["capabilities"]
    tools = mcp_server.handle(rpc("tools/list", mid=2), tmp_path)["result"]["tools"]
    assert len(tools) == 7 and {t["name"] for t in tools} == SEVEN
    assert all(t["description"] and t["inputSchema"]["type"] == "object" for t in tools)


def test_required_inputs_are_the_ones_the_demo_and_runbook_use():
    required = {t["name"]: set(t["inputSchema"].get("required", [])) for t in mcp_server.TOOLS}
    assert required == {"declare_intent": {"intent"}, "record_decision": {"text", "source"},
                        "explain_block": set(), "list_decisions": set(), "list_evidence": set(),
                        "submit_claims": {"claims"}, "hall_pass": set()}


def test_a_failing_tool_answers_with_isError(tmp_path):
    r = call("no_such_tool", {}, tmp_path)
    assert r["isError"] is True and "unknown tool" in r["content"][0]["text"]
    r = call("declare_intent", {"files": ["app/x.py"]}, tmp_path)  # the required intent is missing
    assert r["isError"] is True and "KeyError" in r["content"][0]["text"]
    r = call("list_decisions", {}, tmp_path)
    assert r["isError"] is False and r["content"] == [{"type": "text", "text": "No active decisions."}]


def test_ping_unknown_methods_and_notifications(tmp_path):
    assert mcp_server.handle(rpc("ping"), tmp_path)["result"] == {}
    assert mcp_server.handle(rpc("resources/list"), tmp_path)["error"]["code"] == -32601
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, tmp_path) is None


def test_every_call_is_logged_with_its_caller(tmp_path):
    call("list_evidence", {"agent": "explore-subagent-1"}, tmp_path)
    ev =[e for e in Store(tmp_path).events() if e["stage"] == "mcp_call"][-1]
    assert ev["tool"] == "list_evidence" and ev["agent"] == "explore-subagent-1" and ev["arg_keys"] == ["agent"]


def test_explain_block_and_list_evidence_without_jev(tmp_path):
    store = Store(tmp_path)
    assert "No unexplained blocks" in call("explain_block", {}, tmp_path)["content"][0]["text"]
    store.record_block("write_file", "app/auth.py", "Hall Monitor: declare your intent first.")
    text = call("explain_block", {}, tmp_path)["content"][0]["text"]
    assert text == "write_file on app/auth.py:\nHall Monitor: declare your intent first."
    assert "No unexplained blocks" in call("explain_block", {}, tmp_path)["content"][0]["text"]  # explained once
    assert "No receipts yet" in call("list_evidence", {}, tmp_path)["content"][0]["text"]


def test_hall_pass_tool_writes_the_report(tmp_path):
    text = call("hall_pass", {}, tmp_path)["content"][0]["text"]
    assert "Hall Pass:" in text and (tmp_path / ".hallmonitor" / "hall-pass.html").exists()


def test_a_real_stdio_session_with_the_entry_script(tmp_path):
    """hm_mcp.py started the way Bob starts it: HM_ROOT set, JSON-RPC lines on stdin. Only tools that
    don't ask Jev are called, because the subprocess is outside the no-real-Jev fixture."""
    msgs = [rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}}, 1),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            rpc("tools/list", mid=2),
            rpc("tools/call", {"name": "list_decisions", "arguments": {}}, 3),
            rpc("tools/call", {"name": "no_such_tool", "arguments": {}}, 4)]
    env = {**os.environ, "HM_ROOT": str(tmp_path), "HM_DISABLE_BOB_SHELL": "1"}
    r = subprocess.run([sys.executable, str(ROOT / "hm_mcp.py")], input="\n".join(map(json.dumps, msgs)) + "\n",
                       capture_output=True, text=True, encoding="utf-8", env=env, cwd=tmp_path, timeout=60)
    out = [json.loads(line) for line in r.stdout.splitlines() if line.strip()]
    assert [o["id"] for o in out] == [1, 2, 3, 4], r.stderr  # the notification gets no reply
    assert {t["name"] for t in out[1]["result"]["tools"]} == SEVEN
    assert out[2]["result"] == {"content": [{"type": "text", "text": "No active decisions."}], "isError": False}
    assert out[3]["result"]["isError"] is True
