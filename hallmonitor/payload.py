"""Normalize Bob hook payloads.

Bob 2.0.2 has been observed sending both an IBM-docs shape ({event, tool, input}) and a runtime
shape ({hook_event_name, tool_name, tool_input, ...}); accept either.
"""
import json
import re
from pathlib import Path

EDIT_TOOLS = {"write_file", "write_to_file", "apply_diff", "search_and_replace", "insert_content", "office_edit"}
COMMAND_TOOLS = {"execute_command", "run_command", "shell"}
SPAWN_TOOLS = {"spawn_subagent", "start_subtask", "new_task"}
# Tools Hall Monitor only logs (and keeps out of .bob/ and .hallmonitor/): everything else Bob can call, including
# other servers' MCP tools. Hall Monitor's own MCP tools are never judged.
LOG_ONLY_TOOLS = {"create_html_artifact", "use_mcp_tool", "access_mcp_resource"}
OWN_TOOLS = {"declare_intent", "explain_block", "record_decision", "list_decisions", "list_evidence",
             "submit_claims", "hall_pass"}


def is_own_tool(name):
    return str(name).split("__")[-1] in OWN_TOOLS


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


# Bob IDE 2.2.1 expands a slash command before UserPromptSubmit: the prompt is the command file with its front matter
# as plain lines, then what the user typed after the command (real Bob IDE, Oct 15):
# "name: decisions\ndescription: '...'\nmetadata:\n\nUse the extract-decisions skill on $1. ...\n\n\ndocs/x.pdf"
EXPANDED_RE = re.compile(r"\A\s*name:[ \t]*([\w.-]+)[ \t]*\n[ \t]*description:[ \t]*(.*)\n(?:[ \t]*metadata:.*\n)?")
TYPED_RE = re.compile(r"\A\s*/([\w.-]+)(?:[ \t]+(.*?))?\s*\Z", re.S)


def _command_body(root, name):
    """The body of the command file `name`, after its front matter, if the repo has one in .bob/commands/."""
    try:
        text = (Path(root) / ".bob" / "commands" / f"{name}.md").read_text(encoding="utf-8")
    except (OSError, TypeError):
        return None
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).strip() or None


def slash_command(text, root=None):
    """(name, description, what the user typed after it) when the prompt is a slash command, typed or as Bob expanded
    it, else None. The body is the command's own wording, not something the user said in this conversation."""
    m = TYPED_RE.match(text or "")
    if m and (root is None or _command_body(root, m[1])):  # "/fix the login bug" is a request, not a command
        return m[1], "", (m[2] or "").strip()
    m = EXPANDED_RE.match(text or "")
    if not m:
        return None
    rest = text[m.end():].strip()
    body = _command_body(root, m[1]) if root else None
    if body and body in rest:
        args = rest[rest.index(body) + len(body):]
    else:  # Bob puts what the user typed after the body, past two blank lines
        parts = re.split(r"\n[ \t]*\n[ \t]*\n", rest)
        args = parts[-1] if len(parts) > 1 else ""
    return m[1], m[2].strip().strip("'\""), args.strip()


def describe(tool_name, inp):
    """Return (path, command, detail) for a tool call."""
    path = first(inp, "path", "file_path", "target_file", "output_path", "file")
    command = first(inp, "command", "cmd")
    if tool_name in ("search_and_replace",):
        detail = f"replace:\n{first(inp, 'search', default='')}\nwith:\n{first(inp, 'replace', default='')}"
    else:
        detail = first(inp, "content", "diff", "new_content", "text", default="") or ""
    if command and not path:
        detail = command
    return path, command, str(detail)[:20000]  # a safety cap; step.pre_tool marks what Jev doesn't see


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
    """(brief, preset) from a spawn_subagent input. Bob 2.2.0 sends {name, description}, where `name` is
    the preset ("explore", "general"), not a unique name (probe, Sept 27); other shapes are still accepted."""
    brief = text_of(first(inp, "task", "prompt", "instructions", "description", "message", "query",
                          "objective", default="")) or json.dumps(inp)[:1500]
    kind = str(first(inp, "type", "subagent_type", "preset", "agent_type", "name", default="general")).lower()
    return brief, kind
