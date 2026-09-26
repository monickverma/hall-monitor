# Review pilot: with and without Hall Monitor

About 15 minutes per person. It measures two things, as a small pilot:
- **over-reliance**: how many false claims a reviewer accepts;
- **time**: minutes per claim.

Both are measured without Hall Monitor and with it.

## What you do
1. Find your form. Reviewers r1 and r3 use **Form A**; r2 and r4 use **Form B**.
2. Open part 1, `form_<X>_1_without.csv`. Start a timer. For each claim, read the diff file it points to
   (in `diffs/`) and decide: would you accept this claim about this change, as written? Put `y` or `n`
   in your `accept_rN` column.
3. Stop the timer and write your minutes in `minutes.csv`.
4. Do the same for part 2, `form_<X>_2_with.csv`. It shows Hall Monitor's verdict and reason for each
   claim. Hall Monitor can be wrong, so judge the claim yourself.
5. Don't look at part 2 before finishing part 1, and don't compare answers with anyone.

The claims come from seeded variants of the demo task. Some are false on purpose.

## Then
`python eval/score.py` reports over-reliance and minutes per claim, each with its number of reviewers.
Quote it as a pilot with its n, not as a general result.
