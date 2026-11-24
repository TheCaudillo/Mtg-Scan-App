"""Scryfall mirror ingest + validation/resolution guarantees (no hallucinated printings)."""
from scanner.match.base import VisualHit
from scanner.models import VisionRead


def test_sync_schema_and_filters(db):
    idx = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"ix_cards_name", "ix_cards_set_cn", "ix_cards_illustration", "ix_cards_oracle"} <= idx
    assert db.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.by_id("arena") is None  # digital-only filtered
    assert db.count() == 11


def test_lookups(db):
    assert {r.set_code for r in db.by_name("Cathar Commando")} == {"mid", "inr", "fdn", "dbl"}
    assert [r.id for r in db.by_name("comando cataro")] == ["cc-mid-es"]  # accent-insensitive printed name
    assert db.by_set_cn("MID", "010")[0].name == "Cathar Commando"  # zero padding / case tolerant
    assert {r.id for r in db.by_illustration("ill-cathar")} == {"cc-mid", "cc-inr", "cc-fdn"}


def test_exact_set_and_number_resolves(resolver):
    read = VisionRead(name="Cathar Commando", set_code="mid", collector_number="10", language="en")
    r = resolver.resolve([VisualHit("ill-cathar", "cc-fdn", 0.91)], read, "test")
    assert r.selected.scryfall_id == "cc-mid"
    assert r.confidence >= 0.95
    assert "same_art_reprint" not in r.review_reasons


def test_same_art_reprint_needs_review(resolver):
    r = resolver.resolve([VisualHit("ill-cathar", "cc-fdn", 0.93)], None, "clip")
    assert r.needs_review
    assert "same_art_reprint" in r.review_reasons
    ids = {p.scryfall_id for p in r.candidates}
    assert {"cc-mid", "cc-inr", "cc-fdn"} <= ids
    assert 2 <= len(r.candidates) <= 4


def test_never_hallucinates_unknown_set(resolver):
    r = resolver.resolve([], VisionRead(set_code="zzz", collector_number="999"), "vision")
    assert r.selected is None and r.review_reasons == ["no_match"]
    # name is right but the read set code doesn't exist: only real printings are returned
    r = resolver.resolve([], VisionRead(name="Cathar Commando", set_code="zzz", collector_number="999"), "vision")
    assert r.selected is not None
    assert r.selected.set_code in {"mid", "inr", "fdn", "dbl"}
    assert all(p.set_code != "zzz" for p in r.candidates)


def test_glare_hidden_number_offers_candidates(resolver):
    r = resolver.resolve([], VisionRead(name="Cathar Commando", collector_number=None), "vision")
    assert r.needs_review
    assert "collector_number_unreadable" in r.review_reasons


def test_visual_text_conflict(resolver):
    r = resolver.resolve([VisualHit("ill-sword", "sword", 0.95)], VisionRead(name="Totally Different Name"), "x")
    assert r.selected.name == "Sword of Once and Future"  # name not in DB → visual wins
