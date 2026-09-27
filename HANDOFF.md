# Handoff to the next session (local, on the Windows machine with Bob Shell)

This file lives on branch `claude/trusting-ptolemy-3rlhs0`; don't merge it into main. Written Sun Sept 27 2026,
after PR #12 was merged. It replaces the handoff on `cloud-handoff`. The repo is PUBLIC: never commit keys or
personal information.

## State

- `main` is at 12589f8 (PR #12 merged). It holds `scripts/real_run.py` and fixes for the causes of the Sept 27
  re-run failures:
  - (a) D2 applies only to comparisons. A subject word that names an operation (`receipts.OPERATIONS`, for now
    "comparison") is touched only by a changed line outside the tests that compares something (`==`, `!=`,
    `compare`, `eq(`, `__eq__`). That line must name the subject, or sit in a file whose path, changed lines or
    text mention the rest of it. Replacing `hmac.compare_digest` with `==` in app/auth.py still applies the rule.
  - (b) A project rule that comes back NEEDS EVIDENCE again on the same diff becomes CAN'T CHECK (`ask_user`):
    Bob asks the user, and the round isn't a send-back. The Hall Pass stamps it ASKS YOU. Session key:
    `rules_needing_evidence`.
  - (c) Every task in `scripts/real_run.py` starts with the policy's rules D1-D5 recorded, and its prompt says
    so, so Bob doesn't try to read the PDF. Caps: test-first $1.20, subagents $2.50.
  - (d) Sabotage skips every line of a multi-line string (`gitutil.string_lines`). Before, a docstring's
    "returns True" -> "returns False" survived every round of the subagents run.
  - (e) `eval/scorecard.py` reads a run's final state as the Hall Pass does, including the Stop hook's round.
- Checks on main:
  - pytest: 172 pass. CI is green on Ubuntu and Windows, Python 3.11 and 3.13.
  - control set: 20/20;
  - `simulate.py`: VERIFIED, 9 stops, 0 errors;
  - seeded eval: 21/22 caught, 2/38 false alarms, Brier 0.0349.
- Scorecard: 7.2/10. Robustness is 5.5, a hand-set quality number in `eval/scorecard.py` RUBRIC. With (e):
  - main's 10 runs: 2 ended verified, not 3;
  - with the 4 runs on `real-runs-2026-09-27`: 2 of 14 ended verified and 5 of 14 stuck.
  - No new run has shown the fixes working yet. Don't raise robustness without runs that justify it.
- Branches:
  - `real-runs-2026-09-27` (not merged): the 4 Sept 27 re-runs made through Antigravity.
    - Its logs are clean: no local paths, emails or key values.
    - It conflicts with main only in `eval/scorecard.md`, a generated file: merge, then run
      `python eval/scorecard.py`.
    - Its subagents folder is named `_sent-back`, but the run ended STUCK (its Hall Pass says so). The
      scorecard now counts it as stuck; the folder name can stay.
  - `claude/quirky-cray-hkfi89`: fully in main; can be deleted.
  - `claude/lucid-maxwell-9igfw3` (not merged, no PR): DEMO_SCRIPT.md, a 5-minute voice-over and shot list for
    the submission video, linked from BOB_RUNBOOK step 3. Its research citations are marked [CONFIRM] until
    they are checked.
  - `cloud-handoff`: the old handoff; out of date.

## Open work, highest value first

1. Paid re-runs. They need the user's go-ahead for each run; this machine has Bob Shell.
   - First: `git checkout main && git pull`. Check that `TYPESAFE_API_KEY` and `BOB_API_KEY` are set in the
     environment (`setx` on Windows). Never print them.
   - Run:
     - `python scripts/real_run.py subagents --folder C:/hm-runs/subagents` (cap $2.50)
     - `python scripts/real_run.py test-first --folder C:/hm-runs/test-first` (cap $1.20)

     Add `--dry-run` to see the setup and prompt without starting Bob.
   - Don't re-run protected-path or wrong-jev-key: both already showed their safety property.
   - What to look for in each kept log (`eval/real_runs/<date>_<task>_<outcome>/.hallmonitor/`):
     - D2 is `verified / not_applicable` in `receipts.md`, unless Bob changed a comparison in password code;
     - no surviving mutant on a docstring line;
     - test-first has no `python -c` step on `docs/security-policy.pdf`;
     - a rule that needs evidence twice shows ASKS YOU, not STUCK;
     - whether the round-2 NEEDS EVIDENCE on Bob's own window-eviction test claim, and D5 going to audit in
       round 1, come back. Those weren't fixed.
   - Then:
     - commit the new run folders on a branch;
     - merge `real-runs-2026-09-27` into it and regenerate the scorecard with `python eval/scorecard.py`;
     - update the robustness RUBRIC text in `eval/scorecard.py` honestly;
     - open a PR to main.
2. People only: the IDE evidence (BOB_RUNBOOK.md steps 3-4). This covers the demo run into `demo/bob_run/`,
   task C in `docs/statements.md`, and screenshots in `bob_sessions/`; the user pushes branch `bob-ide-evidence`.
   When they do:
   - check those files for names and emails;
   - fill in the "What Bob built" table in BOB_RUNBOOK.md;
   - run `python eval/scorecard.py`;
   - open a PR to main.

   Don't touch these files otherwise.
3. People only: `needs_person` labels in `eval/review_queue_sample.csv`. Never fill these yourself.
4. Small, free:
   - `hallmonitor/report.py:273` has an f-string with no placeholders (pyflakes).
   - The Receipts audit tier's `bob run --mode hm-auditor` output came back `unparsed` in the subagents run,
     so its cost isn't in that run's $2.03.

## Checks before any PR

`pip install typesafe-sdk pytest reportlab`, then:

- `python -m pytest -q`;
- `python eval/control_set.py` (real Jev, about a cent);
- `python simulate.py`;
- `python eval/seeded.py`, then `python eval/score.py`.

The seeded eval rewrites the review forms in `eval/review/` with timing noise only; restore them with
`git checkout -- eval/review/` unless their content really changed.

## Rules

- Keys only from the environment (`TYPESAFE_API_KEY`, `BOB_API_KEY`). Never print or commit them.
- Don't touch `bob_sessions/`, `docs/statements.md` or `demo/bob_run/` except to check and file what the user
  pushed.
- Don't change harm weights, thresholds or question wording without re-running the control set and the seeded
  eval.
- Work on a branch and open a PR to main. Merge with a merge commit, after CI is green. Paid runs and merges need
  the user's go-ahead.
- Keep 7 MCP tools and 5 hooks.
