"""Hall Pass content added in v4.2, kept out of report.write_hall_pass, which calls extra() once.

- Pseudo-tested: functions whose whole body can be replaced without failing a test (mutation.py).
"""
from html import escape


def _e(x):
    return escape(str(x if x is not None else ""))


def pseudo_tested(receipts):
    sab = (receipts or {}).get("sabotage") or {}
    if not sab.get("extreme_mutants"):
        return ""
    found = sab.get("pseudo_tested") or []
    if found:
        what = " · ".join(f'<span class="target">{_e(p["function"])}</span> (body replaced with '
                          f'<span class="target">{_e(p["body_replaced_with"])}</span>)' for p in found)
        return (f'<tr><td class="stage">pseudo-tested</td><td class="why"><span class="pattern">Pseudo-tested:</span> '
                f'{what}. The tests still pass without these functions.</td></tr>')
    return (f'<tr><td class="stage">pseudo-tested</td><td class="why">Pseudo-tested: none. Each of the '
            f'{sab["extreme_mutants"]} changed functions tried was caught when its body was replaced.</td></tr>')


def extra(store, receipts):
    """HTML for the v4.2 panels, placed right after the Receipts section."""
    rows = pseudo_tested(receipts)
    return f"<section><table>{rows}</table></section>" if rows else ""
