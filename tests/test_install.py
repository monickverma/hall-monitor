"""scripts/install.py merges into an existing .bob/, keeps other custom modes, and is idempotent."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEVEN = {"declare_intent", "record_decision", "explain_block", "list_decisions", "list_evidence",
         "submit_claims", "hall_pass"}
OTHER_MODE = """customModes:
  - slug: reviewer
    name: Reviewer
    roleDefinition: Reviews code.
    groups:
      - read
"""


def load_install():
    spec = importlib.util.spec_from_file_location("hm_install", ROOT / "scripts" / "install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(repo):
    return {p: (repo / p).read_text(encoding="utf-8") for p in
            (".bob/settings.json", ".bob/mcp.json", ".bob/custom_modes.yaml", ".gitignore")}


def test_install_merges_existing_files_and_is_idempotent(tmp_path, capsys):
    repo = tmp_path / "repo"
    (repo / ".bob").mkdir(parents=True)
    (repo / ".bob" / "settings.json").write_text(json.dumps({
        "theme": "dark", "hooks": {"Notification": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}))
    (repo / ".bob" / "mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "other-server"}}}))
    (repo / ".bob" / "custom_modes.yaml").write_text(OTHER_MODE)
    (repo / ".gitignore").write_text("node_modules/\n")
    install = load_install()
    install.main(repo)
    first = snapshot(repo)
    install.main(repo)
    assert snapshot(repo) == first  # a second install changes nothing

    settings = json.loads(first[".bob/settings.json"])
    assert settings["theme"] == "dark" and "Notification" in settings["hooks"]
    assert {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"} <= set(settings["hooks"])
    pre = settings["hooks"]["PreToolUse"][0]
    assert pre["matcher"] == install.TOOLS and "hm_hook.py" in pre["hooks"][0]["command"]
    for tool in ("write_file", "search_and_replace", "insert_content", "execute_command", "spawn_subagent"):
        assert tool in install.TOOLS
    servers = json.loads(first[".bob/mcp.json"])["mcpServers"]
    assert servers["other"] == {"command": "other-server"}
    assert set(servers["hall-monitor"]["alwaysAllow"]) == SEVEN
    assert servers["hall-monitor"]["env"]["HM_ROOT"] == repo.resolve().as_posix()
    assert servers["hall-monitor"]["env"]["TYPESAFE_API_KEY"] == "${env:TYPESAFE_API_KEY}"  # a reference, never the key
    modes = first[".bob/custom_modes.yaml"]
    assert modes.startswith(OTHER_MODE.rstrip()) and modes.count(install.MARKER) == 1
    assert "slug: supervised" in modes
    assert first[".gitignore"].splitlines() == ["node_modules/", ".hallmonitor/"]
    assert (repo / ".bob" / "skills" / "hall-monitor-protocol" / "SKILL.md").exists()
    assert (repo / ".bob" / "commands" / "receipts.md").exists()
    assert "Hall Monitor installed" in capsys.readouterr().out


def test_install_into_a_fresh_repo_writes_our_modes_as_they_are(tmp_path, capsys):
    repo = tmp_path / "fresh"
    repo.mkdir()
    load_install().main(repo)
    assert (repo / ".bob" / "custom_modes.yaml").read_text(encoding="utf-8") == \
        (ROOT / "bob" / "custom_modes.yaml").read_text(encoding="utf-8")
    assert json.loads((repo / ".bob" / "settings.json").read_text())["hooks"]["Stop"]
