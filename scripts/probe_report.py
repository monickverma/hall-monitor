"""Summarize a probe session: what Bob's hooks actually sent, and the answers Hall Monitor depends on.

Usage: python scripts/probe_report.py <repo>
Reads <repo>/.hallmonitor/probe.jsonl (hook payloads) and events.jsonl (MCP calls, if the hall-monitor
MCP server was connected during the probe).
"""
import json
import sys
from collections import defaultdict
from pathlib import Path


def load(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def field(p, *keys):
    for k in keys:
        if isinstance(p, dict) and k in p:
            return p[k]
    return None


def main(repo):
    sys.stdout.reconfigure(encoding="utf-8")
    d = Path(repo) / ".hallmonitor"
    rows = load(d / "probe.jsonl")
    if not rows:
        sys.exit(f"No probe data in {d}. Install with --probe and follow PROBE.md first.")
    events, keys, tool_keys, sessions = defaultdict(int), defaultdict(set), defaultdict(set), defaultdict(set)
    spawns = []
    for i, r in enumerate(rows):
        p = r["payload"]
        ev = field(p, "event", "hook_event_name") or "?"
        tool = field(p, "tool", "tool_name")
        inp = field(p, "input", "tool_input")
        events[ev] += 1
        keys[ev] |= set(p) if isinstance(p, dict) else set()
        if tool and isinstance(inp, dict):
            tool_keys[tool] |= set(inp)
        sessions[field(p, "session_id")].add(ev)
        if tool == "spawn_subagent":
            spawns.append((i, ev, p))

    print("1. Events seen:", dict(events))
    print("\n2. Top-level payload keys per event:")
    for ev, ks in keys.items():
        print(f"   {ev}: {sorted(ks)}")
    print("\n3. Tool input keys per tool (Hall Monitor's payload.py must read these):")
    for t, ks in sorted(tool_keys.items()):
        print(f"   {t}: {sorted(ks)}")
    print("\n4. Assistant text in any payload?",
          any(any(k in (r["payload"] or {}) for k in ("assistant_message", "message", "last_assistant_message"))
              for r in rows if isinstance(r["payload"], dict)))

    print("\n5. Subagents:")
    pre = [i for i, ev, _ in spawns if ev == "PreToolUse"]
    post = [i for i, ev, _ in spawns if ev == "PostToolUse"]
    print(f"   spawn_subagent PreToolUse: {len(pre)}  PostToolUse: {len(post)}")
    if spawns:
        print("   spawn input example:", json.dumps(field(spawns[0][2], "input", "tool_input"))[:300])
    inside = 0
    for a, b in zip(pre, post):
        inside += sum(1 for r in rows[a + 1:b]
                      if field(r["payload"], "event", "hook_event_name") in ("PreToolUse", "PostToolUse")
                      and field(r["payload"], "tool", "tool_name") != "spawn_subagent")
    print(f"   hook events between a subagent's spawn and its return: {inside}"
          f" -> hooks {'DO' if inside else 'probably do NOT'} fire inside subagents"
          " (check that the subagent actually used tools)")
    print(f"   distinct session_ids: {len(sessions)} {dict((str(k)[:12], sorted(v)) for k, v in sessions.items())}")

    calls = [e for e in load(d / "events.jsonl") if e.get("stage") == "mcp_call"]
    if calls:
        agents = defaultdict(int)
        for c in calls:
            agents[c.get("agent") or "main/unspecified"] += 1
        print("\n6. hall-monitor MCP calls by agent:", dict(agents),
              "-> subagents CAN call MCP" if any(a not in ("main", "main/unspecified") for a in agents) else "")
    else:
        print("\n6. No hall-monitor MCP calls logged (was the MCP server connected?)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
