"""Everything Hall Monitor remembers lives in <repo>/.hallmonitor/ as JSON / JSONL."""
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CONFIG = {
    "test_command": "python -m pytest -q",
    "claims_file": "CLAIMS.md",
    "plan_globs": ["PLAN.md", "*plan*.md"],
    "fail_open": True,
    "require_intent": True,
    "safe_commands": r"^\s*(python -m pytest|pytest|npm test|git (status|diff|log|show)\b|ls\b|dir\b|cat\b|type\b)",
    "bob_audit_cost": 4.0,
    "escalate_cost": 3.0,
    "claim_escalate_cost": 1.5,
    "human_cost": 6.0,
    "uncertain_band": [0.2, 0.8],  # Jev answers outside this band count as settled
    "max_brief_chars": 1500,
    "max_mutants": 4,
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.dir = self.root / ".hallmonitor"
        self.dir.mkdir(exist_ok=True)
        ignore = self.dir / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n")

    def _json(self, name, default):
        p = self.dir / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

    def _write(self, name, data):
        (self.dir / name).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _jsonl(self, name):
        p = self.dir / name
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

    def _append(self, name, row):
        with open(self.dir / name, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    # config -----------------------------------------------------------------
    def config(self):
        return {**DEFAULT_CONFIG, **self._json("config.json", {})}

    # session ----------------------------------------------------------------
    def session(self):
        s = self._json("session.json", {})
        for k, v in {"goal": None, "base": None, "actions": [], "commands": [], "notes": [],
                     "intents": [], "blocks": [], "flags": [], "off_task_streak": 0}.items():
            s.setdefault(k, v)
        return s

    def save_session(self, s):
        s["actions"] = s["actions"][-20:]
        s["commands"] = s["commands"][-10:]
        s["intents"] = s["intents"][-40:]
        self._write("session.json", s)

    # blocks: hook stderr only reaches Bob's logs, so reasons are kept for the explain_block MCP tool
    def record_block(self, tool, target, reason):
        s = self.session()
        s["blocks"] = (s["blocks"] + [{"t": time.time(), "tool": tool, "target": target, "reason": reason,
                                       "explained": False}])[-20:]
        self.save_session(s)

    def unexplained_blocks(self, n=3):
        s = self.session()
        todo = [b for b in s["blocks"] if not b["explained"]][-n:]
        for b in todo:
            b["explained"] = True
        self.save_session(s)
        return todo

    def add_flag(self, text):
        s = self.session()
        s["flags"] = (s["flags"] + [text])[-10:]
        self.save_session(s)

    def pop_flags(self):
        s = self.session()
        flags, s["flags"] = s["flags"], []
        self.save_session(s)
        return flags

    # declared intents (MCP declare_intent) -------------------------------------------
    def add_intent(self, row):
        s = self.session()
        row = {"id": f"I{len(s['intents']) + 1}", "t": time.time(), **row}
        s["intents"].append(row)
        self.save_session(s)
        return row

    def revoke_intent(self, intent_id, why):
        """An intent whose action did something else is burned: no further edits or conflict checks use it."""
        s = self.session()
        for it in s["intents"]:
            if it["id"] == intent_id:
                it["verdict"], it["why"] = "rejected", f"revoked: {why}"
        self.save_session(s)

    def intent_for(self, path=None, command=None, max_age=1800):
        """Most recent non-rejected intent (any agent) covering this file or command; else the most
        recent rejected one, so a rejected plan stays blocked; else None."""
        norm = lambda x: str(x).replace("\\", "/").lstrip("./").lower()
        rejected = None
        for it in reversed(self.session()["intents"]):
            if time.time() - it["t"] > max_age:
                break
            covers = (path and norm(path) in {norm(f) for f in it.get("files", [])}) or \
                (command and any(command.strip().startswith(c.strip()) or c.strip().startswith(command.strip())
                                 for c in it.get("commands", []) if c.strip()))
            if covers and it["verdict"] != "rejected":
                return it
            if covers and rejected is None:
                rejected = it
        return rejected

    def active_intents(self, exclude_agent=None, max_age=1800):
        return [it for it in self.session()["intents"]
                if time.time() - it["t"] <= max_age and it["verdict"] != "rejected"
                and it.get("agent") != exclude_agent]

    def queue_note(self, text):
        s = self.session()
        if text not in s["notes"]:
            s["notes"].append(text)
        self.save_session(s)

    def pop_notes(self):
        s = self.session()
        notes, s["notes"] = s["notes"], []
        self.save_session(s)
        return notes

    # decision ledger: append-only, decisions are superseded, never overwritten ----------------
    def ledger(self):
        return self._jsonl("ledger.jsonl")

    def active_decisions(self, kind=None):
        rows = self.ledger()
        dead = {r["supersedes"] for r in rows if r.get("supersedes")}
        return [r for r in rows if r["id"] not in dead and (kind is None or r.get("kind") == kind)]

    def add_decision(self, text, source, kind="limit", supersedes=None):
        row = {"id": f"D{len(self.ledger()) + 1}", "text": text, "source": source, "kind": kind,
               "recorded_at": now(), "supersedes": supersedes}
        self._append("ledger.jsonl", row)
        return row

    def agents_md_decisions(self):
        """Bullets under a '## Decisions' heading in AGENTS.md (imported once, when the ledger is empty)."""
        p = self.root / "AGENTS.md"
        if self.ledger() or not p.exists():
            return []
        m = re.search(r"^##\s*Decisions\s*$(.*?)(?=^##\s|\Z)", p.read_text(encoding="utf-8"), re.M | re.S)
        return [re.sub(r"^\s*[-*]\s+", "", l).strip() for l in (m[1] if m else "").splitlines()
                if re.match(r"\s*[-*]\s+\S", l)]

    # event log (feeds the dashboard) ------------------------------------------
    def log(self, row):
        self._append("events.jsonl", {"ts": now(), "t": time.time(), **row})

    def events(self):
        return self._jsonl("events.jsonl")

    def write_report(self, name, text):
        (self.dir / name).write_text(text, encoding="utf-8")
