"""Evidence collection: what changed, a fresh test run, sabotage probes, and checkpoints."""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def git(root, *args, env=None):
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, **env} if env else None)
    return r.stdout


def head(root):
    return git(root, "rev-parse", "HEAD").strip() or None


def tracked_files(root):
    return [f for f in git(root, "ls-files").splitlines() if f]


def checkpoint(root, n, last_tree=None):
    """Snapshot the working tree as refs/hallmonitor/C<n>.

    Uses a private index file, then commit-tree and update-ref, so the working tree, the real index and
    the branch are never touched. Returns {ref, commit, tree}, or None if nothing changed since the
    last checkpoint (`last_tree`) or this isn't a git repository.
    """
    root = Path(root)
    env = {"GIT_INDEX_FILE": str(root / ".hallmonitor" / "cp.index"),
           "GIT_AUTHOR_NAME": "Hall Monitor", "GIT_AUTHOR_EMAIL": "hall-monitor@localhost",
           "GIT_COMMITTER_NAME": "Hall Monitor", "GIT_COMMITTER_EMAIL": "hall-monitor@localhost"}
    parent = head(root)
    if parent:
        git(root, "read-tree", "HEAD", env=env)
    git(root, "add", "-A", env=env)
    tree = git(root, "write-tree", env=env).strip()
    if not tree or tree == last_tree:
        return None
    commit = git(root, "commit-tree", tree, "-m", f"hall monitor checkpoint C{n}",
                 *(["-p", parent] if parent else []), env=env).strip()
    if not commit:
        return None
    ref = f"refs/hallmonitor/C{n}"
    git(root, "update-ref", ref, commit)
    return {"ref": ref, "commit": commit, "tree": tree}


def diff_from(root, ref):
    """What changed in the working tree since a checkpoint (tracked files)."""
    return git(root, "diff", ref)


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


def run_tests(root, cmd, timeout=120, copy=False):
    """Run the test command in `root`. With copy=True (`root` is a scratch copy of the repo), the copy
    goes first on PYTHONPATH, so an editable install of the original can't answer for it, and no bytecode
    is written, so two mutants of one file can't share a stale .pyc."""
    env = None
    if copy:
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONPATH": os.pathsep.join([str(root)] + [p for p in [os.environ.get("PYTHONPATH")] if p])}
    try:
        r = subprocess.run(cmd, cwd=root, shell=True, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=env)
        tail = (r.stdout + r.stderr).strip().splitlines()[-6:]
        return {"command": cmd, "passed": r.returncode == 0, "exit_code": r.returncode, "tail": tail}
    except subprocess.TimeoutExpired:
        return {"command": cmd, "passed": False, "exit_code": None, "tail": ["timed out"]}


COPY_SKIP = {".git", ".hallmonitor", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".tox"}


def copy_tree(root, dest):
    """Copy what `git add -A` would snapshot (tracked plus untracked, not ignored) into `dest`, for
    mutants that must never touch the working tree."""
    root, dest = Path(root), Path(dest)
    files = git(root, "ls-files", "-co", "--exclude-standard").splitlines()
    if not files:  # not a git repository: copy the tree, minus caches and Hall Monitor's own state
        shutil.copytree(root, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*COPY_SKIP, "*.pyc"))
        return
    for f in files:
        src = root / f
        if src.is_file() and not f.endswith(".pyc") and not COPY_SKIP & set(Path(f).parts):
            (dest / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / f)


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


def plan_mutants(root, changes_, max_mutants=4):
    """(path, lineno, original line, mutated line) for up to `max_mutants` changed, non-test source lines."""
    plan = []
    for path, c in changes_.items():
        if is_test(path) or not path.endswith(".py"):
            continue
        lines = (Path(root) / path).read_text(encoding="utf-8").splitlines(keepends=True)
        for lineno, text in c["added"]:
            if len(plan) >= max_mutants:
                return plan
            if SKIP.match(text) or lineno < 1 or lineno > len(lines):
                continue
            for pat, rep in MUTATORS:
                mutated = re.sub(pat, rep, lines[lineno - 1], count=1)
                if mutated != lines[lineno - 1]:
                    plan.append((path, lineno, text, mutated))
                    break
    return plan


def sabotage(root, changes_, cmd, max_mutants=4):
    """Break changed source lines one at a time and rerun the tests.

    A surviving mutant (tests still pass on broken code) means the tests do not check that code.
    The mutants run in a scratch copy of the repository, so the working tree is never touched: a
    parallel subagent can't read a mutated file or lose an edit to the restore, the IDE never shows a
    file flicker, and a hook killed mid-run can't leave a mutant behind. If the unmutated copy fails its
    tests (a file the tests need is ignored by git, say), the mutants run in place, as before v4.2.
    """
    plan = plan_mutants(root, changes_, max_mutants)
    if not plan:
        return {"mutants": 0, "killed": 0, "survived": []}
    results = []
    with tempfile.TemporaryDirectory(prefix="hm-sabotage-") as tmp:
        copy_tree(root, tmp)
        in_copy = run_tests(tmp, cmd, timeout=60, copy=True)["passed"]
        where = tmp if in_copy else root
        for path, lineno, text, mutated in plan:
            p = Path(where) / path
            original = p.read_text(encoding="utf-8")
            lines = original.splitlines(keepends=True)
            try:
                p.write_text("".join(lines[:lineno - 1] + [mutated] + lines[lineno:]), encoding="utf-8")
                killed = not run_tests(where, cmd, timeout=60, copy=in_copy)["passed"]
            finally:
                p.write_text(original, encoding="utf-8")
            results.append({"file": path, "line": lineno, "from": text.strip(),
                            "to": mutated.strip(), "killed": killed})
    survived = [r for r in results if not r["killed"]]
    return {"mutants": len(results), "killed": len(results) - len(survived), "survived": survived}
