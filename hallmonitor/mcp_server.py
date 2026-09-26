"""Hall Monitor MCP server (stdio, no dependencies). Registered in .bob/mcp.json.

Hooks can block Bob but can't talk back to it. MCP tools can, so every judgment Bob asks for
(intent, decision, claims) comes back as a tool result it reads in the same turn. Anything Hall Monitor
noticed in the meantime (a failed step, a stall, a drifted subagent) goes at the top of the next of these
results, so it reaches Bob during the task rather than at the user's next message.
"""
import json
import os
import sys
import traceback

from . import evidence, jev, ledger, receipts, report, step
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
    {"name": "list_evidence",
     "description": "List your receipts: every edit and command you ran in this task, numbered E1, E2, ..., "
                    "newest first, with test runs marked PASS or FAIL. Call it before submit_claims and cite the "
                    "IDs that prove each claim.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "submit_claims",
     "description": "Call when you believe the task is done. Submit one claim per thing you did, each citing the "
                    "receipt IDs (from list_evidence) that prove it, e.g. {\"claim\": \"Added tests that fail if "
                    "the 6th attempt is allowed\", \"evidence\": [\"E7\", \"E9\"]}. For claims about tests, cite a "
                    "test run made after your last edit. Each claim is checked against its receipts, the diff, a "
                    "fresh test run and sabotage probes. Fix anything not verified and submit again. If an AUDIT "
                    "is requested, spawn the explore subagent as instructed and pass its findings in audit_notes.",
     "inputSchema": {"type": "object", "required": ["claims"], "properties": {
         "claims": {"type": "array", "items": {"anyOf": [
             {"type": "object", "required": ["claim"], "properties": {
                 "claim": {**S, "description": "One specific thing you did"},
                 "evidence": {"type": "array", "items": S, "description": "Receipt IDs, e.g. [\"E7\", \"E9\"]"}}},
             {**S, "description": "A claim as plain text; inline citations like [E7] count"}]}},
         "audit_notes": {"type": "object", "description": "Claim index -> the explore subagent's findings",
                         "additionalProperties": S}}}},
    {"name": "hall_pass",
     "description": "Write the Hall Pass HTML report for this session (timeline, catches, decisions, receipts, "
                    "cost) and return its path and a short summary.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def pending(store, name):
    """Notes and flags Bob hasn't seen yet, delivered once. explain_block gives the full reason for a
    block, so the short "Blocked ..." pointers are dropped there."""
    items = store.pop_pending()
    if name == "explain_block":
        items = [x for x in items if not x.startswith("Blocked ")]
    return ("Hall Monitor notes before you continue:\n" + "\n".join(f"- {x}" for x in items) + "\n\n") if items else ""


def call(name, args, store):
    """Every tool result starts with the notes Bob hasn't seen yet. If Jev refuses a request, the tool
    answers that Hall Monitor couldn't check it, instead of failing."""
    prefix = pending(store, name)
    try:
        return prefix + _call(name, args, store)
    except jev.JevRefused:
        store.log({"stage": "error", "tool": name, "fallback": "jev_refused", "error": "Jev refused the request"})
        return prefix + f"Hall Monitor couldn't check this ({name}). Ask the user how to proceed."


def _call(name, args, store):
    if name == "declare_intent":
        return step.declare_intent(store, args["intent"], args.get("files") or [], args.get("commands") or [],
                                   args.get("agent") or "main", args.get("agent_task"))
    if name == "record_decision":
        return ledger.record_decision(store, args["text"], args["source"], args.get("quote"))
    if name == "list_decisions":
        return ledger.list_decisions(store)
    if name == "list_evidence":
        return evidence.list_evidence(store)
    if name == "explain_block":
        blocks = store.unexplained_blocks()
        if not blocks:
            return "No unexplained blocks. If a tool was blocked, declare an intent for it with declare_intent first."
        return "\n\n".join(f"{b['tool']} on {b['target']}:\n{b['reason']}" for b in blocks)
    if name == "submit_claims":
        return receipts.message(receipts.verify(store, args["claims"], args.get("audit_notes")))
    if name == "hall_pass":
        path, summary = report.write_hall_pass(store)
        return f"{summary}\nHall Pass: {path}"
    raise ValueError(f"unknown tool {name}")


def handle(msg, root):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        result = {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "hall-monitor", "version": "0.4.0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params", {})
        store = Store(root)
        # Every call is logged with its caller-supplied agent, which also answers "can subagents call MCP?"
        args = p.get("arguments") or {}
        store.log({"stage": "mcp_call", "tool": p.get("name"), "agent": args.get("agent"),
                   "arg_keys": sorted(args.keys()),
                   # the probe checks whether Bob can send an array of objects (evidence-carrying claims)
                   "claim_types": sorted({type(c).__name__ for c in args.get("claims") or []}) or None})
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
