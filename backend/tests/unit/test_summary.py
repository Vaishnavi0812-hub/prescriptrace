from app.core.engine.model import CheckResult
from app.core.recalls import CHECKLIST, RecallResult
from app.core.summary import summarise
from tests.unit.test_recalls import ALL, TELMA, check_recalls


def empty() -> CheckResult:
    return CheckResult((), (), 0, (), {})


def test_recall_alerts_count_once_per_medicine() -> None:
    recalls = check_recalls([TELMA], ALL + ALL)  # duplicate records for one medicine
    summary = summarise(empty(), recalls, checked=1, unresolved=0)
    assert summary.needs_attention == 1
    assert summary.headline == "1 thing needs attention"


def test_careful_no_issue_headline() -> None:
    summary = summarise(empty(), RecallResult((), (), CHECKLIST), checked=2, unresolved=0)
    assert summary.headline == "No known issues found in our data"


def test_nothing_checked_yet() -> None:
    assert summarise(None, None, 0, 2).headline == "Please confirm the medicines first"
    assert summarise(None, None, 0, 0).headline == "Add medicines to check"
