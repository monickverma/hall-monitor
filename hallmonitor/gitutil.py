"""Evidence collection: what changed, a fresh test run, sabotage probes, and checkpoints."""
import ast
import io
import os
import re
import shutil
import subprocess
import tempfile
import time
import tokenize
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
    env = {"GIT_INDEX_FILE": str(root / ".hallmonitor" / "cp.index"), **AUTHOR}
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


AUTHOR = {"GIT_AUTHOR_NAME": "Hall Monitor", "GIT_AUTHOR_EMAIL": "hall-monitor@localhost",
          "GIT_COMMITTER_NAME": "Hall Monitor", "GIT_COMMITTER_EMAIL": "hall-monitor@localhost"}


def worktree_tree(root):
    """The working tree as a git tree (tracked plus untracked, not ignored), or None. Written through a scratch copy of
    the index, so the real index, the branch and the working tree are never touched, and git reuses the index's file
    stats instead of hashing every file again."""
    with tempfile.TemporaryDirectory(prefix="hm-index-", ignore_cleanup_errors=True) as tmp:
        index = Path(tmp) / "index"
        real = Path(root) / git(root, "rev-parse", "--git-path", "index").strip()
        if real.is_file():
            shutil.copyfile(real, index)
        env = {"GIT_INDEX_FILE": str(index)}
        git(root, "add", "-A", env=env)
        return git(root, "write-tree", env=env).strip() or None


def snapshot(root, ref):
    """The tree as it is now, uncommitted work included, as a commit on HEAD kept under `ref`: what a new task's or a
    subagent's claims are judged against. HEAD itself when nothing is uncommitted; None before the first commit.
    Real Bob IDE, Oct 15: a docstring task started with the last task's rate-limit work still uncommitted, and judged
    against HEAD, its "docstrings only, no behavior changes" came back CONTRADICTED until the task was STUCK."""
    parent = head(root)
    tree = worktree_tree(root) if parent else None
    if not tree or tree == git(root, "rev-parse", "HEAD^{tree}").strip():
        return parent
    commit = git(root, "commit-tree", tree, "-p", parent, "-m", f"hall monitor base {ref}", env=AUTHOR).strip()
    if not commit:
        return parent
    git(root, "update-ref", ref, commit)
    return commit


def diff_args(root, base):
    """What `git diff` compares to see the changes since `base`. Against HEAD, the working tree (untracked files are
    added by the caller). Against an older commit, such as a snapshot() with work that was untracked then, the working
    tree's own tree, so a file untracked then and now is compared, not shown as deleted and new."""
    if base and base != head(root):
        tree = worktree_tree(root)
        if tree:
            return ["--no-renames", base, tree]
    return [base or "HEAD", "--"]


def diff_from(root, ref):
    """What changed in the working tree since a checkpoint (tracked files)."""
    return git(root, "diff", ref)


def changes(root, base):
    """Added lines per changed file since `base`, including untracked files.

    Returns {path: {"status": "modified"|"new", "added": [(lineno, text)], "removed": int,
    "removed_lines": [text]}}.
    """
    out = {}
    cur, born = None, False
    args = diff_args(root, base)
    trees = args[-1] != "--"
    for line in git(root, "diff", "--unified=0", *args).splitlines():
        if line.startswith("--- "):
            born = line.endswith("/dev/null")
        elif line.startswith("+++ "):
            cur = None if line.endswith("/dev/null") else line[6:]
            if cur:
                out.setdefault(cur, {"status": "new" if trees and born else "modified", "added": [], "removed": 0,
                                     "removed_lines": []})
        elif line.startswith("@@") and cur:
            new_start = int(re.match(r"@@ -\S+ \+(\d+)", line)[1])
            out[cur]["_next"] = new_start
        elif cur and line.startswith("+"):
            n = out[cur].get("_next", 0)
            out[cur]["added"].append((n, line[1:]))
            out[cur]["_next"] = n + 1
        elif cur and line.startswith("-") and not line.startswith("---"):
            out[cur]["removed"] += 1
            out[cur]["removed_lines"].append(line[1:])
    untracked = [] if trees else git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    for f in untracked:  # already in the diff when it compares trees
        p = Path(root) / f
        if p.is_file():
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            out[f] = {"status": "new", "added": list(enumerate(lines, 1)), "removed": 0, "removed_lines": []}
    for v in out.values():
        v.pop("_next", None)
    return out


def diff_text(changes_, max_chars=3500, max_lines=200):
    # Real Bob, Sept 27: at 60 lines per file, Jev never saw most of a long doc edit, so true claims about
    # it came back "says nothing". Say what's left out, so a cut is never read as an absence.
    # An added line numbered None is a marker a caller put in (receipts' excerpts), shown as is.
    parts = []
    for path, c in changes_.items():
        added = c["added"]
        body = "\n".join(t if n is None else f"+{t}" for n, t in added[:max_lines])
        if len(added) > max_lines:
            body += f"\n[... {len(added) - max_lines} more added lines not shown]"
        parts.append(f"--- {path} ({c['status']}, +{c.get('total_added', len(added))} -{c['removed']})\n{body}")
    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n[... {len(text) - max_chars} more characters of the diff not shown]"
    return text


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
            try:
                shutil.copy2(src, dest / f)
            except OSError:  # a locked file: the copy's own test run shows whether it mattered
                continue


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


def fail_before(root, base, changes_, cmd, timeout=120):
    """Fail-before/pass-after (v4 design): the changed tests, run in a scratch copy where the changed code is
    put back as it was at `base`. Tests that pass there don't check the change. None when the change holds
    no Python tests or no Python code, or there's no base to compare with."""
    tests = sorted(f for f in changes_ if is_test(f) and f.endswith(".py"))
    code = sorted(f for f in changes_ if not is_test(f) and f.endswith(".py"))
    if not tests or not code or not base:
        return None
    with tempfile.TemporaryDirectory(prefix="hm-before-") as tmp:
        copy_tree(root, tmp)
        existed = set(git(root, "ls-tree", "-r", "--name-only", base, "--", *code).splitlines())
        for f in code:
            if f in existed:
                (Path(tmp) / f).write_text(git(root, "show", f"{base}:{f}"), encoding="utf-8")
            else:
                (Path(tmp) / f).unlink(missing_ok=True)
        r = run_tests(tmp, cmd, timeout=timeout, copy=True)
    return {"changed_tests": tests, "code_put_back": code,
            "on_code_before_change": "pass" if r["passed"] else "fail", "tail": r["tail"][-3:]}


def string_lines(text):
    """Line numbers a multi-line string spans, such as a docstring's prose. Real Bob, Sept 27 (subagents, $2.03):
    "allowed (returns True)" in a docstring became "allowed (returns False)", survived every round because no
    test can catch it, and Bob spent its turns trying to kill it."""
    rows = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.STRING and tok.end[0] > tok.start[0]:
                rows.update(range(tok.start[0], tok.end[0] + 1))
    except (tokenize.TokenError, SyntaxError):  # a file that doesn't parse: mutate its lines as before
        pass
    return rows


def inert_lines(text):
    """Line numbers of a Python file that do nothing when it runs: blank lines, comments, and string statements
    such as docstrings. None when the file doesn't parse."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    rows = {n for n, line in enumerate(text.splitlines(), 1) if not line.strip() or line.strip().startswith("#")}
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            rows.update(range(node.lineno, node.end_lineno + 1))
    return rows


def _removed(root, args, path):
    """(line number at the base, text) of each line removed from `path` since the base (`args`: diff_args)."""
    out, n = [], None
    for line in git(root, "diff", "--unified=0", *args, *([] if args[-1] == "--" else ["--"]), path).splitlines():
        if line.startswith("@@"):
            n = int(re.match(r"@@ -(\d+)", line)[1])
        elif n is not None and line.startswith("-") and not line.startswith("---"):
            out.append((n, line[1:]))
            n += 1
    return out


def behavior_lines(root, base, changes_):
    """(path, line) of each changed line outside the tests that can change what the code does: every added or
    removed line except blank lines, comments and docstrings. Other files count whole, except dotfiles such as
    .gitignore. Real Bob, Sept 27: a task that only added a docstring to app/__init__.py was held to "Every
    behavior change must ship with a test that fails without the change", and Jev contradicted it."""
    out, args = [], None
    for path, c in changes_.items():
        if is_test(path) or Path(path).name.startswith("."):
            continue
        if c["status"] == "modified" and args is None:
            args = diff_args(root, base)
        removed = _removed(root, args, path) if c["status"] == "modified" else []
        if not path.endswith(".py"):
            out += [(path, n) for n, _ in c["added"]] + [(path, -n) for n, _ in removed]
            continue
        now = inert_lines((Path(root) / path).read_text(encoding="utf-8", errors="replace"))
        then = inert_lines(git(root, "show", f"{base}:{path}")) if removed else set()
        if now is None or then is None:  # a file that doesn't parse counts whole
            now, then = set(), set()
        out += [(path, n) for n, _ in c["added"] if n not in now]
        out += [(path, -n) for n, _ in removed if n not in then]
    return out


def plan_mutants(root, changes_, max_mutants=4):
    """(path, lineno, original line, mutated line) for up to `max_mutants` changed, non-test source lines, leaving
    out comments, definitions, imports and the prose of multi-line strings."""
    plan = []
    for path, c in changes_.items():
        if is_test(path) or not path.endswith(".py"):
            continue
        lines = (Path(root) / path).read_text(encoding="utf-8").splitlines(keepends=True)
        prose = string_lines("".join(lines))
        for lineno, text in c["added"]:
            if len(plan) >= max_mutants:
                return plan
            if SKIP.match(text) or lineno in prose or lineno < 1 or lineno > len(lines):
                continue
            for pat, rep in MUTATORS:
                mutated = re.sub(pat, rep, lines[lineno - 1], count=1)
                if mutated != lines[lineno - 1]:
                    plan.append((path, lineno, text, mutated))
                    break
    return plan


def sabotage(root, changes_, cmd, max_mutants=4, deadline=None):
    """Break changed source lines one at a time and rerun the tests.

    A surviving mutant (tests still pass on broken code) means the tests do not check that code.
    The mutants run in a scratch copy of the repository, so the working tree is never touched: a
    parallel subagent can't read a mutated file or lose an edit to the restore, the IDE never shows a
    file flicker, and a hook killed mid-run can't leave a mutant behind. If the unmutated copy fails its
    tests (a file the tests need is ignored by git, say), no mutants run. Past `deadline` (time.time()) no further
    mutant starts, so a Receipts round answers Bob in time; the ones run still count.
    """
    plan = plan_mutants(root, changes_, max_mutants)
    if not plan:
        return {"mutants": 0, "killed": 0, "survived": []}
    results = []
    with tempfile.TemporaryDirectory(prefix="hm-sabotage-", ignore_cleanup_errors=True) as tmp:
        copy_tree(root, tmp)
        # The working tree is never mutated: a parallel subagent's edit made during a mutant's run was lost to the
        # restore, and a tree failing for another reason scored every mutant killed (audit sweep, Sept 28). If the
        # copy can't pass its tests, there is no sabotage evidence, and Receipts says so.
        if not run_tests(tmp, cmd, timeout=60, copy=True)["passed"]:
            return {"mutants": 0, "killed": 0, "survived": [], "skipped": "the tests don't pass in a clean copy"}
        where, in_copy = tmp, True
        for path, lineno, text, mutated in plan:
            if deadline and time.time() > deadline:
                break
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
    out = {"mutants": len(results), "killed": len(results) - len(survived), "survived": survived}
    if len(results) < len(plan):
        out["note"] = f"time budget used up after {len(results)} of {len(plan)} mutants"
    return out
