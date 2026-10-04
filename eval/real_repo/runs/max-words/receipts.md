# Receipts

Status: **accept** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED |  | jev | E1, E3 | Added max_words parameter to _modern_slugify() in slugify/slugify.py: after stopwords filtering, splits on the internal separator and keeps at most max_words words when max_words > 0; 0 means no limit. |
| VERIFIED |  | jev | E1, E3 | Added max_words keyword-only parameter (default 0) to the public slugify() function; passing a non-zero value with algorithm='legacy' raises ValueError; the value is forwarded to _modern_slugify() only for algorithm='modern'. |
| VERIFIED |  | jev | E2, E3 | Created tests/test_max_words.py with 9 tests covering: basic 3-word limit, single word, exact count, larger-than-count (no truncation), max_words=0 (no limit), default (no limit), custom separator, interaction with stopwords (max_words applied after stopword removal), and ValueError on algorithm='legacy'. |
| VERIFIED | same_as_before | jev_deep | E3 | All 9 new tests and all 82 frozen legacy tests pass (91 total) after the edits. |
| VERIFIED | same_as_before | jev |  | The finished work satisfies the project rule D5: "New or changed behavior is covered by tests in a separate file under tests/." |

Fresh test run: pass (`python -m pytest -q tests`)
Sabotage: 2/2 mutants killed
Changed tests on the code before the change: FAIL (good: they check the change)
