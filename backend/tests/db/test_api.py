"""HTTP API end to end (TestClient + real database)."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.limiter import limiter
from app.api.v1 import settings
from app.main import app
from app.services.state import get_state

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("require_db")]


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:  # runs the lifespan: loads the vocabulary
        yield c


@pytest.fixture
def ready(client: TestClient) -> TestClient:
    if not get_state().ready:
        pytest.skip("drug data not loaded")
    return client


def check(client: TestClient, *items: dict[str, Any], **context: Any) -> dict[str, Any]:
    body = {"items": [{"id": f"m{i}", **it} for i, it in enumerate(items)], "context": context}
    response = client.post("/api/v1/check", json=body)
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------ search / normalise


def test_search_shows_brand_and_generic(ready: TestClient) -> None:
    hits = ready.get("/api/v1/drugs/search", params={"q": "dolo"}).json()["hits"]
    assert hits[0]["label"] == "Dolo 650"
    assert hits[0]["ingredient_names"] == ["acetaminophen"]


def test_search_is_typo_tolerant(ready: TestClient) -> None:
    hits = ready.get("/api/v1/drugs/search", params={"q": "paracetmol"}).json()["hits"]
    assert any(h["ingredient_names"] == ["acetaminophen"] for h in hits)


def test_normalise_reports_status_and_candidates(ready: TestClient) -> None:
    body = {"lines": ["Crocin 650", "itopride 50", "Augmentin 625"]}
    results = ready.post("/api/v1/normalise", json=body).json()["results"]
    assert [r["status"] for r in results] == ["resolved", "unknown", "resolved"]
    assert set(results[2]["best"]["ingredient_names"]) == {"amoxicillin", "clavulanate"}
    assert results[2]["strengths"] == [{"value": "625", "unit": None}]


# ------------------------------------------------------------------ check


def test_check_full_response(ready: TestClient) -> None:
    out = check(
        ready,
        {"text": "Warfarin 5mg"},
        {"text": "Ecosprin 75"},
        {"text": "Combiflam"},
        age_group="older",
    )
    summary = out["summary"]
    assert summary["checked_medicines"] == 3 and summary["unresolved"] == 0
    assert summary["needs_attention"] >= 2
    assert summary["headline"].endswith("need attention")
    top = out["findings"][0]
    assert top["severity"] in ("contraindicated", "major")
    assert top["evidence"] and top["evidence"][0]["dataset_name"]
    assert any(f["rule_id"] == "BLEEDING_STACK" for f in out["findings"])
    assert out["notes"] and {n["context"] for n in out["notes"]} == {"geriatric"}
    assert out["recalls"]["checklist"]
    assert "not proof" in out["absence_note"]
    assert any(d["code"] == "ddinter" for d in out["data_versions"])


def test_unresolved_items_are_never_guessed(ready: TestClient) -> None:
    out = check(ready, {"text": "Warfarin 5mg"}, {"text": "itopride 50"})
    assert out["summary"]["checked_medicines"] == 1
    (unresolved,) = out["unresolved"]
    assert unresolved["id"] == "m1" and unresolved["status"] == "unknown"
    assert all("m1" not in f["medicines"] for f in out["findings"])


def test_user_selection_is_used(ready: TestClient) -> None:
    pick = ready.post("/api/v1/normalise", json={"lines": ["amlodipin"]}).json()["results"][0]
    best = pick["best"]
    item = {
        "text": "amlodipin",
        "selection": {
            "ref": best["ref"],
            "label": best["label"],
            "ingredients": best["ingredients"],
        },
    }
    out = check(ready, item, {"text": "Simvastatin 40"})
    assert out["medicines"][0]["how"] == "selected"
    assert out["summary"]["unresolved"] == 0


def test_counterfeit_batch_flag_via_api(ready: TestClient) -> None:
    out = check(ready, {"text": "Telma 40", "batch": "K18230707"})
    flags = out["recalls"]["flags"]
    if not flags:
        pytest.skip("CDSCO alerts not loaded")
    assert flags[0]["match"] == "batch" and flags[0]["level"] == "serious"
    assert out["summary"]["needs_attention"] >= 1


def test_no_issues_headline_is_careful(ready: TestClient) -> None:
    out = check(ready, {"text": "Metformin 500"})
    if out["summary"]["needs_attention"] == 0 and out["summary"]["worth_checking"] == 0:
        assert out["summary"]["headline"] == "No known issues found in our data"


# ------------------------------------------------------------------ validation & limits


@pytest.mark.parametrize(
    "body",
    [
        {"items": []},
        {"items": [{"id": "a", "text": ""}]},
        {"items": [{"id": "a", "text": "x" * 121}]},
        {"items": [{"id": "a", "text": "x"}, {"id": "a", "text": "y"}]},
        {"items": [{"id": "a", "text": f"d{i}"} for i in range(21)]},
        {"items": [{"id": "a b", "text": "x"}]},
        {"items": [{"id": "a", "text": "x", "batch": "<script>"}]},
        {"items": [{"id": "a", "text": "x", "selection": {"label": "x", "ingredients": ["DROP"]}}]},
        {"items": [{"id": "a", "text": "x"}], "context": {"age_group": "baby"}},
    ],
)
def test_invalid_requests_are_rejected(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post("/api/v1/check", json=body).status_code == 422


def test_unknown_selected_ingredient_is_rejected(ready: TestClient) -> None:
    body = {
        "items": [
            {"id": "a", "text": "x", "selection": {"label": "x", "ingredients": ["999999999"]}}
        ]
    }
    assert ready.post("/api/v1/check", json=body).status_code == 422


def test_rate_limit_returns_429(ready: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_search", "2/minute")
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()
    codes = [ready.get("/api/v1/drugs/search", params={"q": "dolo"}).status_code for _ in range(3)]
    limiter.reset()
    assert codes == [200, 200, 429]


# ------------------------------------------------------------------ meta


def test_datasets_lists_licences_and_limitations(client: TestClient) -> None:
    body = client.get("/api/v1/datasets").json()
    if not body["datasets"]:
        pytest.skip("no datasets loaded")
    ddinter = next(d for d in body["datasets"] if d["code"] == "ddinter")
    assert "non-commercial" in ddinter["licence"].lower()
    assert "CC BY-NC-SA" in body["non_commercial_notice"]
    assert all(d["licence"] for d in body["datasets"])


def test_health_reports_search_readiness(client: TestClient) -> None:
    body = client.get("/api/v1/health").json()
    assert body["database"] is True and "search_ready" in body


def test_openapi_documents_all_endpoints(client: TestClient) -> None:
    paths = set(client.get("/api/openapi.json").json()["paths"])
    assert {
        "/api/v1/check",
        "/api/v1/normalise",
        "/api/v1/drugs/search",
        "/api/v1/datasets",
        "/api/v1/health",
    } <= paths


def test_generic_names_are_not_brand_matched_to_recalls(ready: TestClient) -> None:
    out = check(ready, {"text": "Warfarin 5mg"}, {"text": "Sertraline 50"})
    assert out["recalls"]["flags"] == []  # only same-ingredient summaries, never "related"


# ------------------------------------------------------------------ OCR


def test_ocr_reads_a_printed_prescription(ready: TestClient) -> None:
    import shutil

    if shutil.which("tesseract") is None:
        pytest.skip("tesseract not installed")
    from app.core.ocr.synthetic import render

    image = render(["Tab. Dolo 650 1-0-1", "Cap. Omez 20 mg OD"])
    response = ready.post("/api/v1/ocr", files={"file": ("rx.png", image, "image/png")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "tesseract" and body["sends_image_off_device"] is False
    meds = [line for line in body["lines"] if line["likely_medicine"]]
    names = [
        set(line["normalised"]["best"]["ingredient_names"])
        for line in meds
        if line["normalised"] and line["normalised"]["best"]
    ]
    assert names == [{"acetaminophen"}, {"omeprazole"}]
    assert all(line["crop_png_b64"] for line in meds)
    assert all(
        line["crop_png_b64"] is None for line in body["lines"] if not line["likely_medicine"]
    )


@pytest.mark.parametrize(
    ("content", "ctype", "status"),
    [(b"%PDF-1.7", "application/pdf", 415), (b"not really a png", "image/png", 422)],
)
def test_ocr_rejects_non_images(ready: TestClient, content: bytes, ctype: str, status: int) -> None:
    response = ready.post("/api/v1/ocr", files={"file": ("x", content, ctype)})
    assert response.status_code == status


def test_ocr_rejects_oversized_uploads(ready: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ocr_max_bytes", 1000)
    response = ready.post("/api/v1/ocr", files={"file": ("x.png", b"0" * 2000, "image/png")})
    assert response.status_code == 413


# ------------------------------------------------------------------ offline pack


def test_offline_pack_is_sourced_and_cacheable(ready: TestClient) -> None:
    meta = ready.get("/api/v1/offline-pack/meta").json()
    response = ready.get("/api/v1/offline-pack")
    assert response.status_code == 200
    assert response.headers["etag"] == f'"{meta["version"]}"'
    pack = response.json()
    assert pack["version"] == meta["version"]
    assert "CC BY-NC-SA" in pack["licence_notice"]
    rx = {name: i for i, (_, name) in enumerate(pack["ingredients"])}
    # Warfarin + aspirin is a serious DDInter pair; every fact keeps its record id and URL.
    pair = next(p for p in pack["pairs"] if {p[0], p[1]} == {rx["warfarin"], rx["aspirin"]})
    for ds, sev, ref, url, *_ in pair[2]:
        assert ref and pack["severities"][sev] in ("contraindicated", "major", "moderate", "minor")
        if pack["pair_datasets"][ds] == "ddinter":
            assert (pack["url_prefixes"][ds] + url).startswith("https://ddinter2.scbdd.com/")
    assert any(row[0] == "Dolo 650" for row in pack["names"])
    not_modified = ready.get(
        "/api/v1/offline-pack", headers={"If-None-Match": response.headers["etag"]}
    )
    assert not_modified.status_code == 304
