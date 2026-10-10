"""One plain-language headline for a check result (pure; reused by the offline app).

Policy (ADR-011): "need attention" = contraindicated or major findings, and serious recall
flags; "worth checking" = moderate findings and recall warnings; everything else (minor, not
graded, information) is listed but not counted in the headline.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.engine.model import CheckResult
from app.core.recalls.match import RecallResult

ATTENTION = {"contraindicated", "major"}
WORTH_CHECKING = {"moderate"}


@dataclass(frozen=True)
class Summary:
    headline: str
    needs_attention: int
    worth_checking: int
    other: int
    checked_medicines: int
    unresolved: int


def summarise(
    result: CheckResult | None, recalls: RecallResult | None, checked: int, unresolved: int
) -> Summary:
    findings = result.findings if result else ()
    flags = recalls.flags if recalls else ()
    # Recalls count once per medicine at its most serious level (three alert records about the
    # same pack are one thing to act on, not three).
    serious = {f.medicine_id for f in flags if f.level == "serious"}
    warning = {f.medicine_id for f in flags if f.level == "warning"} - serious
    attention = sum(1 for f in findings if f.severity in ATTENTION) + len(serious)
    worth = sum(1 for f in findings if f.severity in WORTH_CHECKING) + len(warning)
    other = sum(1 for f in findings if f.severity not in ATTENTION | WORTH_CHECKING)
    other += len({f.medicine_id for f in flags} - serious - warning)
    return Summary(
        headline=_headline(attention, worth, checked, unresolved),
        needs_attention=attention,
        worth_checking=worth,
        other=other,
        checked_medicines=checked,
        unresolved=unresolved,
    )


def _headline(attention: int, worth: int, checked: int, unresolved: int) -> str:
    if checked == 0:
        return "Add medicines to check" if not unresolved else "Please confirm the medicines first"
    if attention:
        noun = "thing needs" if attention == 1 else "things need"
        return f"{attention} {noun} attention"
    if worth:
        noun = "thing is" if worth == 1 else "things are"
        return f"{worth} {noun} worth checking"
    # Careful wording: absence from our data is not proof of safety.
    return "No known issues found in our data"
