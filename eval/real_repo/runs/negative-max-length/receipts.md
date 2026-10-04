# Receipts

Status: **accept** (send-backs so far: 0)

| State | Reason | Judged by | Cites | Claim |
|---|---|---|---|---|
| VERIFIED |  | jev | E1, E3 | Added a ValueError raise with a clear message (including the offending value) in _modern_slugify in slugify/slugify.py when max_length is negative; the legacy path is not affected |
| VERIFIED |  | jev | E2, E3 | Added a new test file tests/test_negative_max_length.py covering: ValueError raised for -1, ValueError raised for large negatives, error message contains 'max_length' and the value, zero is allowed (no limit), positive values are allowed, and legacy algorithm is not affected by the new validation |
| VERIFIED |  | jev |  | The finished work satisfies the project rule D5: "New or changed behavior is covered by tests in a separate file under tests/." |

Fresh test run: pass (`python -m pytest -q tests`)
Sabotage: 1/1 mutants killed
Changed tests on the code before the change: FAIL (good: they check the change)
