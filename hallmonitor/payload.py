"""Normalize Bob hook payloads.

Bob 2.0.2 has been observed sending both an IBM-docs shape ({event, tool, input}) and a runtime
shape ({hook_event_name, tool_name, tool_input, ...}); accept either.
"""
import json

EDIT_TOOLS = {"write_file", "write_to_file", "apply_diff", "search_and_replace", "insert_content"}
COMMAND_TOOLS = {"execute_command", "run_command", "shell"}
SPAWN_TOOLS = {"spawn_subagent"}


def first(d, *keys, default=None):
    for k in keys:
        v = d.get(k) if isinstance(d, dict) else None
        if v not in (None, ""):
            return v
    return default


def event(p):
    return first(p, "hook_event_name", "event", default="")


def tool(p):
    return first(p, "tool_name", "tool", default="")


def tool_input(p):
    v = first(p, "tool_input", "input", default={})
    return v if isinstance(v, dict) else {"value": v}


def text_of(v):
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return first(v, "content", "text", "message", default="") or ""
    if isinstance(v, list):
        return "\n".join(text_of(x) for x in v)
    return ""


def assistant_text(p):
    """The agent's own words around this event, if Bob includes them (used as `stated_reason`)."""
    return text_of(first(p, "assistant_message", "last_assistant_message", "assistant_text",
                         "message", "reason", default=""))


def prompt(p):
    return text_of(first(p, "prompt", "user_prompt", "user_message", "message", default=""))


def describe(tool_name, inp):
    """Return (path, command, detail) for a tool call."""
    path = first(inp, "path", "file_path", "target_file")
    command = first(inp, "command", "cmd")
    if tool_name in ("search_and_replace",):
        detail = f"replace:\n{first(inp, 'search', default='')}\nwith:\n{first(inp, 'replace', default='')}"
    else:
        detail = first(inp, "content", "diff", "new_content", "text", default="") or ""
    if command and not path:
        detail = command
    return path, command, str(detail)[:2500]


def tool_output(p):
    return text_of(first(p, "tool_response", "tool_output", "output", "result", default=""))


def exit_code(p):
    """The command's exit code, if Bob's PostToolUse payload carries one (unverified; the probe checks)."""
    for src in (p, first(p, "tool_response", "tool_output", "output", "result", default={})):
        if isinstance(src, dict):
            v = first(src, "exit_code", "exitCode", "returncode", "return_code")
            if isinstance(v, int) or (isinstance(v, str) and v.lstrip("-").isdigit()):
                return int(v)
    return None


def subagent_brief(inp):
    """(brief, preset) from a spawn_subagent input; field names are unverified, so accept several."""
    brief = text_of(first(inp, "task", "prompt", "instructions", "description", "message", "query",
                          "objective", default="")) or json.dumps(inp)[:1500]
    kind = str(first(inp, "type", "subagent_type", "preset", "agent_type", default="general")).lower()
    return brief, kind
