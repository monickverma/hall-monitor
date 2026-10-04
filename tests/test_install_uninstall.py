"""scripts/install.py keeps a repo's own hooks, servers and modes; --uninstall removes only what it added."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install  # noqa: E402

THEIR_HOOK = {"matcher": "^execute_command$", "hooks": [{"type": "command", "command": "python lint_hook.py"}]}


def repo_with_own_bob_setup(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".bob").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / ".bob" / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [THEIR_HOOK]}, "theme": "dark"}),
                                                 encoding="utf-8")
    (repo / ".bob" / "mcp.json").write_text(json.dumps({"mcpServers": {"github": {"command": "gh-mcp"}}}),
                                            encoding="utf-8")
    (repo / ".bob" / "custom_modes.yaml").write_text("customModes:\n  - slug: reviewer\n    name: Reviewer\n",
                                                     encoding="utf-8")
    return repo


def test_install_keeps_the_repos_own_hooks_and_reinstall_does_not_duplicate_ours(tmp_path):
    repo = repo_with_own_bob_setup(tmp_path)
    install.main(repo)
    install.main(repo)  # a reinstall replaces Hall Monitor's entries, it doesn't add a second set
    settings = json.loads((repo / ".bob" / "settings.json").read_text(encoding="utf-8"))
    pre = settings["hooks"]["PreToolUse"]
    assert THEIR_HOOK in pre and sum(install._ours(e) for e in pre) == 1
    assert settings["theme"] == "dark"
    servers = json.loads((repo / ".bob" / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert set(servers) == {"github", "hall-monitor"}


def test_uninstall_removes_only_what_install_added(tmp_path):
    repo = repo_with_own_bob_setup(tmp_path)
    install.main(repo)
    (repo / ".hallmonitor").mkdir(exist_ok=True)
    (repo / ".hallmonitor" / "events.jsonl").write_text("{}\n", encoding="utf-8")
    install.uninstall(repo)
    settings = json.loads((repo / ".bob" / "settings.json").read_text(encoding="utf-8"))
    assert settings["hooks"] == {"PreToolUse": [THEIR_HOOK]} and settings["theme"] == "dark"
    assert set(json.loads((repo / ".bob" / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]) == {"github"}
    modes = (repo / ".bob" / "custom_modes.yaml").read_text(encoding="utf-8")
    assert "reviewer" in modes and install.MARKER not in modes
    assert not (repo / ".bob" / "skills").exists() and not (repo / ".bob" / "commands").exists()
    assert (repo / ".hallmonitor" / "events.jsonl").exists()  # the records stay


def test_doctor_passes_a_fresh_install_and_names_what_is_missing(tmp_path):
    repo = repo_with_own_bob_setup(tmp_path)
    doctor = [sys.executable, str(ROOT / "scripts" / "doctor.py"), str(repo)]
    before = subprocess.run(doctor, capture_output=True, text=True, timeout=120)
    assert "hook PreToolUse not installed" in before.stdout
    install.main(repo)
    after = subprocess.run(doctor, capture_output=True, text=True, timeout=120)
    repo_lines = [l for l in after.stdout.splitlines() if l.startswith("[") and ("hook " in l or "MCP server" in l or "modes" in l)]
    assert repo_lines and all(l.startswith("[ok  ]") for l in repo_lines), after.stdout


def test_uninstall_from_a_repo_with_no_bob_setup_of_its_own_leaves_no_bob_folder(tmp_path):
    repo = tmp_path / "plain"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    install.main(repo)
    install.uninstall(repo)
    assert not (repo / ".bob").exists()
