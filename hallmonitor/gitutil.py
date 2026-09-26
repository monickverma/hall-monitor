"""Evidence collection: what changed, a fresh test run, and sabotage probes."""
import re
import subprocess
from pathlib import Path


def git(root, *args):
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8")
    return r.stdout


def head(root):
    return git(root, "rev-parse", "HEAD").strip() or None


def tracked_files(root):
    return [f for f in git(root, "ls-files").splitlines() if f]


def changes(root, base):
    """Added lines per changed file since `base`, including untracked files.

    Returns {path: {"status": "modified"|"new", "added": [(lineno, text)], "removed": int}}.
    """
    out = {}
    cur = None
    for line in git(root, "diff", "--unified=0", base or "HEAD", "--").splitlines():
        if line.startswith("+++ "):
            cur = None if line.endswith("/dev/null") else line[6:]
            if cur:
                out.setdefault(cur, {"status": "modified", "added": [], "removed": 0})
        elif line.startswith("@@") and cur:
            new_start = int(re.match(r"@@ -\S+ \+(\d+)", line)[1])
            out[cur]["_next"] = new_start
        elif cur and line.startswith("+"):
            n = out[cur].get("_next", 0)
            out[cur]["added"].append((n, line[1:]))
            out[cur]["_next"] = n + 1
        elif cur and line.startswith("-") and not line.startswith("---"):
            out[cur]["removed"] += 1
    for f in git(root, "ls-files", "--others", "--exclude-standard").splitlines():
        p = Path(root) / f
        if p.is_file():
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            out[f] = {"status": "new", "added": list(enumerate(lines, 1)), "removed": 0}
    for v in out.values():
        v.pop("_next", None)
    return out


def diff_text(changes_, max_chars=3500):
    parts = []
    for path, c in changes_.items():
        body = "\n".join(f"+{t}" for _, t in c["added"][:60])
        parts.append(f"--- {path} ({c['status']}, +{len(c['added'])} -{c['removed']})\n{body}")
    return "\n".join(parts)[:max_chars]


def run_tests(root, cmd, timeout=120):
    try:
        r = subprocess.run(cmd, cwd=root, shell=True, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        tail = (r.stdout + r.stderr).strip().splitlines()[-6:]
        return {"command": cmd, "passed": r.returncode == 0, "exit_code": r.returncode, "tail": tail}
    except subprocess.TimeoutExpired:
        return {"command": cmd, "passed": False, "exit_code": None, "tail": ["timed out"]}


# Mutation operators applied to changed, non-test source lines.
MUTATORS = [
    (r">=", ">"), (r"<=", "<"),
    (r"(?<![-<>=!])>(?![=>])", ">="), (r"(?<![<>=!])<(?![=<])", "<="),
    (r"==", "!="), (r"!=", "=="),
    (r"\bTrue\b", "False"), (r"\bFalse\b", "True"),
    (r"\breturn (?!None\b)(\S.*)$", "return None"),
    (r"\+ 1\b", "- 1"), (r"- 1\b", "+ 1"),
]
SKIP = re.compile(r"^\s*(#|def |class |import |from |@|\"\"\"|'''|$)")


def is_test(path):
    name = Path(path).name
    return name.startswith("test_") or name.endswith("_test.py") or "tests/" in path.replace("\\", "/")


def sabotage(root, changes_, cmd, max_mutants=4):
    """Break changed source lines one at a time and rerun the tests.

    A surviving mutant (tests still pass on broken code) means the tests do not check that code.
    """
    results = []
    for path, c in changes_.items():
        if is_test(path) or not path.endswith(".py"):
            continue
        p = Path(root) / path
        original = p.read_text(encoding="utf-8")
        lines = original.splitlines(keepends=True)
        for lineno, text in c["added"]:
            if len(results) >= max_mutants:
                break
            if SKIP.match(text) or lineno < 1 or lineno > len(lines):
                continue
            for pat, rep in MUTATORS:
                mutated = re.sub(pat, rep, lines[lineno - 1], count=1)
                if mutated != lines[lineno - 1]:
                    break
            else:
                continue
            try:
                p.write_text("".join(lines[:lineno - 1] + [mutated] + lines[lineno:]), encoding="utf-8")
                killed = not run_tests(root, cmd, timeout=60)["passed"]
            finally:
                p.write_text(original, encoding="utf-8")
            results.append({"file": path, "line": lineno, "from": text.strip(),
                            "to": mutated.strip(), "killed": killed})
    survived = [r for r in results if not r["killed"]]
    return {"mutants": len(results), "killed": len(results) - len(survived), "survived": survived}
