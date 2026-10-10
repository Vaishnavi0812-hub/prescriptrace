import urllib.error
from typing import Any

from app.core.normalise import Normaliser, Vocabulary
from app.services.rxnav_external import RxNavSuggestions

VOCAB = Vocabulary({"40790": "pantoprazole"}, [])


def fake_fetch(responses: dict[str, Any]):  # type: ignore[no-untyped-def]
    def fetch(url: str) -> Any:
        for fragment, payload in responses.items():
            if fragment in url:
                return payload
        raise AssertionError(f"unexpected URL {url}")

    return fetch


def test_suggestion_mapped_to_known_ingredient_is_capped_to_confirm() -> None:
    fetch = fake_fetch(
        {
            "approximateTerm": {
                "approximateGroup": {"candidate": [{"rxcui": "999", "name": "Pantocid"}]}
            },
            "rxcui/999/related": {
                "relatedGroup": {"conceptGroup": [{"conceptProperties": [{"rxcui": "40790"}]}]}
            },
        }
    )
    result = Normaliser(VOCAB, external=RxNavSuggestions(VOCAB, fetch)).normalise("Pantocid 40")
    assert result.status == "confirm"
    assert result.best is not None and result.best.ingredient_names == ("pantoprazole",)


def test_suggestions_for_unknown_ingredients_are_dropped() -> None:
    fetch = fake_fetch(
        {
            "approximateTerm": {"approximateGroup": {"candidate": [{"rxcui": "2262278"}]}},
            "rxcui/2262278/related": {"relatedGroup": {"conceptGroup": []}},
        }
    )
    assert RxNavSuggestions(VOCAB, fetch)("crocin") == []


def test_network_failure_means_no_suggestions() -> None:
    def broken(url: str) -> Any:
        raise urllib.error.URLError("offline")

    assert RxNavSuggestions(VOCAB, broken)("anything") == []
