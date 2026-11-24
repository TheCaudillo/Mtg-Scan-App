"""End-to-end API flow on an isolated data dir with the fixture Scryfall DB."""
import importlib
import shutil
import time
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def client(tmp_path, db_path, monkeypatch):
    shutil.copy(db_path, tmp_path / "scryfall.db")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MATCHER_MODE", "ocr")
    monkeypatch.setenv("VISION_PROVIDER", "")
    from scanner import config
    config.get_settings.cache_clear()
    import scanner.api.main as main
    importlib.reload(main)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c
    config.get_settings.cache_clear()


def test_full_flow(client):
    h = client.get("/api/health").json()
    assert h["printings"] == 11

    b = client.post("/api/batches", json={"name": "Test Lot"}).json()
    with open(FIX / "binder_whatsapp.jpg", "rb") as f:
        pages = client.post(f"/api/batches/{b['id']}/pages", files=[("files", ("wa.jpg", f, "image/jpeg"))]).json()
    assert len(pages) == 1 and pages[0]["width"] == 1080

    prev = client.post(f"/api/batches/{b['id']}/pages/{pages[0]['id']}/detect", json={}).json()
    assert len(prev["quads"]) == 9 and prev["chrome_cropped"]

    assert client.post(f"/api/batches/{b['id']}/scan", json={}).json()["queued"] == 1
    for _ in range(300):
        batch = client.get(f"/api/batches/{b['id']}").json()
        if batch["status"] == "done":
            break
        time.sleep(0.2)
    assert batch["status"] == "done"
    assert len(batch["cards"]) == 9
    assert all(c["status"] in ("identified", "needs_review", "unidentified") for c in batch["cards"])
    assert all(c["crop_url"] and c["strip_url"] for c in batch["cards"])
    assert client.get(batch["cards"][0]["crop_url"]).status_code == 200

    # user resolves a card from the drawer: pick printing, then finish, then language
    cid = batch["cards"][0]["id"]
    assert client.patch(f"/api/cards/{cid}", json={"scryfall_id": "does-not-exist"}).status_code == 422
    c = client.patch(f"/api/cards/{cid}", json={"scryfall_id": "cc-dbl"}).json()
    assert c["selected"]["set_code"] == "dbl" and c["status"] == "identified" and c["user_verified"]
    c = client.patch(f"/api/cards/{cid}", json={"finish": "foil"}).json()
    assert c["unit_price_usd"] == 12.49 and c["foil_detection"] == "foil"
    c = client.patch(f"/api/cards/{cid}", json={"lang": "es", "quantity": 2}).json()
    assert c["price_source"] == "english_equivalent" and "non_english" in c["flags"] and c["quantity"] == 2
    assert client.patch(f"/api/cards/{cid}", json={"scryfall_id": "reclaim-9ed", "finish": "foil"}).status_code == 422

    s = client.post(f"/api/batches/{b['id']}/summary", json={"asking_price": 300, "currency": "MXN",
                                                            "fx_rate_mxn_per_usd": 20}).json()
    assert s["liquid_cards"] >= 2 and s["asking_price_usd"] == 15.0

    for fmt in ("csv", "manabox", "moxfield", "markdown"):
        r = client.get(f"/api/batches/{b['id']}/export", params={"format": fmt})
        assert r.status_code == 200 and "Cathar Commando" in r.text, fmt

    wl = client.put("/api/wantlist", json={"text": "2 Cathar Commando\nSol Ring"}).json()
    assert [i["name"] for i in wl["items"]] == ["Cathar Commando", "Sol Ring"]
    assert client.get("/api/search", params={"q": "cathar"}).json()[0]["name"] == "Cathar Commando"
