"""Hall Monitor MCP server (stdio, no dependencies). Registered in .bob/mcp.json.

Hooks can block Bob but can't talk back to it. MCP tools can, so every judgment Bob asks for
(intent, decision, claims) comes back as a tool result it reads in the same turn. Subagents can
call these tools too, which is how parallel subagents get goal checks and conflict checks.
"""
import json
import os
import sys
import traceback

from . import ledger, receipts, report, step
from .hook import repo_root
from .store import Store

S = {"type": "string"}
TOOLS = [
    {"name": "declare_intent",
     "description": "Call BEFORE editing files or running commands. Say what you will do and why, and list "
                    "the files and commands. Hall Monitor checks it against the goal, the recorded decisions and "
                    "other agents' work, and returns approved / approved_with_note / REJECTED. Edits without an "
                    "approved intent are blocked. Subagents: pass agent (your name) and agent_task (your task).",
     "inputSchema": {"type": "object", "required": ["intent"], "properties": {
         "intent": {**S, "description": "What you will do and why, in one or two sentences"},
         "files": {"type": "array", "items": S}, "commands": {"type": "array", "items": S},
         "agent": {**S, "description": "'main' or the subagent's name"},
         "agent_task": {**S, "description": "For subagents: the task you were given"}}}},
    {"name": "record_decision",
     "description": "Record a project decision or rule so it is enforced for the rest of the work. Use it for "
                    "rules you find in policy documents, ADRs or AGENTS.md (source = the file path, quote = the "
                    "exact sentence) and for decisions the user states (source = 'user'). Returns whether it was "
                    "recorded, what it supersedes, or why it was rejected.",
     "inputSchema": {"type": "object", "required": ["text", "source"], "properties": {
         "text": {**S, "description": "The decision, stated as a rule"},
         "source": {**S, "description": "'user', 'agent', or the document path it came from"},
         "quote": {**S, "description": "The exact sentence from the source document"}}}},
    {"name": "explain_block",
     "description": "Call this whenever one of your tool calls is reported as blocked. Bob's hooks can block a tool "
                    "but cannot tell you why; this returns Hall Monitor's reason and what to do instead.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_decisions", "description": "List the active decisions Hall Monitor enforces.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "submit_claims",
     "description": "Call when you believe the task is done. Submit one claim per thing you did (e.g. 'Added "
                    "tests that fail if the 6th attempt is allowed'). Each claim is checked against the diff, a "
                    "fresh test run and sabotage probes. Returns verdicts; fix anything not verified and submit "
                    "again. If an AUDIT is requested, spawn the explore subagent as instructed and pass its "
                    "findings back in audit_notes.",
     "inputSchema": {"type": "object", "required": ["claims"], "properties": {
         "claims": {"type": "array", "items": S},
         "audit_notes": {"type": "object", "description": "Claim index -> the explore subagent's findings",
                         "additionalProperties": S}}}},
    {"name": "hall_pass",
     "description": "Write the Hall Pass HTML report for this session (timeline, catches, decisions, receipts, "
                    "cost) and return its path and a short summary.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def call(name, args, store):
    if name == "declare_intent":
        return step.declare_intent(store, args["intent"], args.get("files") or [], args.get("commands") or [],
                                   args.get("agent") or "main", args.get("agent_task"))
    if name == "record_decision":
        return ledger.record_decision(store, args["text"], args["source"], args.get("quote"))
    if name == "list_decisions":
        return ledger.list_decisions(store)
    if name == "explain_block":
        blocks = store.unexplained_blocks()
        if not blocks:
            return "No unexplained blocks. If a tool was blocked, declare an intent for it with declare_intent first."
        return "\n\n".join(f"{b['tool']} on {b['target']}:\n{b['reason']}" for b in blocks)
    if name == "submit_claims":
        result = receipts.verify(store, args["claims"], args.get("audit_notes"))
        return receipts.message(result)
    if name == "hall_pass":
        path, summary = report.write_hall_pass(store)
        return f"{summary}\nHall Pass: {path}"
    raise ValueError(f"unknown tool {name}")


def handle(msg, root):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        result = {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "hall-monitor", "version": "0.3.0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params", {})
        store = Store(root)
        # Every call is logged with its caller-supplied agent, which also answers "can subagents call MCP?"
        store.log({"stage": "mcp_call", "tool": p.get("name"), "agent": (p.get("arguments") or {}).get("agent"),
                   "arg_keys": sorted((p.get("arguments") or {}).keys())})
        try:
            text, err = call(p["name"], p.get("arguments") or {}, store), False
        except Exception as e:
            text, err = f"Hall Monitor error: {e!r}\n{traceback.format_exc()[-800:]}", True
        result = {"content": [{"type": "text", "text": text}], "isError": err}
    elif method == "ping":
        result = {}
    elif mid is None:
        return None  # notification
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    root = repo_root(os.environ.get("HM_ROOT") or os.getcwd())
    for line in sys.stdin:
        if not line.strip():
            continue
        resp = handle(json.loads(line), root)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    serve()
