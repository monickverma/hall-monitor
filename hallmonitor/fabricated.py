"""Fabricated files (v4.2, tier 0: decided by code, before Jev).

A claim that a code file was created or changed must name a file that exists somewhere: tracked by git,
in the working tree (ignored files included), in the diff since the session base (deleted and renamed
files included), or in an evidence row. A code path that exists nowhere makes the claim CONTRADICTED
with reason code `unknown_file`: "<path> does not exist in this repo."

Receipts.certify runs this check first, so a claim that also names a real changed file is still caught.
"""
import os
import re
from pathlib import Path

from . import gitutil
from .evidence import is_code

PATH_RE = re.compile(r"[A-Za-z0-9_][\w./-]*\.[A-Za-z]{1,5}\b")  # receipts.FILE_RE, plus the position
URL_RE = re.compile(r"\b\w+://\S+")
# Mentions that aren't claims about the file: "instead of utils.py", "without touching helpers.py".
NEGATED = re.compile(r"\b(not|never|without|instead of|rather than|didn't|did not|won't|avoid\w*)\b[^.;]{0,40}$",
                     re.I)
NOT_FILES = {"node.js", "vue.js", "next.js", "nuxt.js", "react.js", "express.js", "d3.js", "three.js", "chart.js",
             "ember.js", "backbone.js", "angular.js", "alpine.js", "p5.js"}  # names of projects, not files
SKIP_DIRS = {".git", ".hallmonitor", ".bob", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".tox"}
MAX_WALK = 20000


def mentioned_paths(claim):
    """Code-file paths the claim asserts something about, in order, as written."""
    text = URL_RE.sub(lambda m: " " * len(m[0]), claim or "")
    text = re.sub(r"(?<![\w./])\./", "  ", text)  # "./app/x.py" is app/x.py
    out = []
    for m in PATH_RE.finditer(text):
        tok = m[0].rstrip(".")
        if not is_code(tok) or tok.lower() in NOT_FILES or tok.startswith("../"):
            continue
        if m.start() and text[m.start() - 1] in "./\\-":  # part of a longer token (a URL or an odd path)
            continue
        if NEGATED.search(text[:m.start()]):
            continue
        out.append(tok)
    return list(dict.fromkeys(out))


def _walk(root):
    """Repo-relative paths of every file in the working tree, ignored ones included (bounded)."""
    root = Path(root)
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        rel = Path(d).relative_to(root).as_posix()
        out += [f if rel == "." else f"{rel}/{f}" for f in files]
        if len(out) > MAX_WALK:
            break
    return out


def _exists(tok, names):
    t = tok.lower()
    return any(n == t or n.endswith("/" + t) for n in names)


# A claim about a file's absence names a file that doesn't exist, and is true. Real Bob, Oct 4 (failed-command): "Ran
# python -m pytest tests/test_missing.py, the file does not exist, so pytest ..." came back CONTRADICTED as unknown_file.
ABSENCE_RE = re.compile(r"\b(do(es)?|did)\s*n[o']t\s+exist|\bnot\s+(found|exist)|\bmissing\b|\bno such file|"
                        r"\bnon-?existent\b", re.I)
CREATION_RE = re.compile(r"\b(add|creat|wr[io]te|writ|implement|introduc)\w*", re.I)


def unknown_files(root, base, claim, known):
    """The code files `claim` names that exist nowhere in the repo (see the module docstring). A claim that says a
    file is absent, and not that it was made, is about that absence (Jev still judges it)."""
    if ABSENCE_RE.search(claim) and not CREATION_RE.search(claim):
        return []
    todo = [t for t in mentioned_paths(claim) if not _exists(t, {k.lower() for k in known})]
    if not todo:
        return []
    names = {n.lower() for n in gitutil.git(root, "diff", "--name-only", "--no-renames", base or "HEAD", "--").splitlines()}
    todo = [t for t in todo if not _exists(t, names) and not (Path(root) / t).exists()]
    if todo:
        walked = {n.lower() for n in _walk(root)}
        todo = [t for t in todo if not _exists(t, walked)]
    return todo


def message(paths):
    return f"{', '.join(paths)} {'does' if len(paths) == 1 else 'do'} not exist in this repo."
