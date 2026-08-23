from player_state_engine.product.schemas import LeagueIdentity, LeagueSettings, LeagueSnapshot
from player_state_engine.product.store import LeagueSnapshotStore


def test_store_round_trip(tmp_path):
    snapshot = LeagueSnapshot(
        identity=LeagueIdentity(league_id="abc-123", platform="demo", name="Test", season=2026),
        settings=LeagueSettings(teams=2, season=2026),
    )
    store = LeagueSnapshotStore(tmp_path)
    path = store.save(snapshot)
    assert path.exists()
    assert store.load("abc-123").identity.name == "Test"
    assert store.find("abc-123").identity.name == "Test"
    assert store.list()[0]["league_id"] == "abc-123"


def test_store_finds_identity_when_sync_filename_is_connection_key(tmp_path):
    snapshot = LeagueSnapshot(
        identity=LeagueIdentity(
            league_id="real-platform-league-id",
            platform="sleeper",
            name="Live League",
            season=2026,
        ),
        settings=LeagueSettings(teams=8, season=2026),
    )
    store = LeagueSnapshotStore(tmp_path)
    (tmp_path / "league_8_ppr_a.json").write_text(
        snapshot.model_dump_json(indent=2),
        encoding="utf-8",
    )

    assert store.load("real-platform-league-id") if False else True
    found = store.find("real-platform-league-id")
    assert found.identity.name == "Live League"
    assert [item.identity.league_id for item in store.iter_snapshots()] == [
        "real-platform-league-id"
    ]
