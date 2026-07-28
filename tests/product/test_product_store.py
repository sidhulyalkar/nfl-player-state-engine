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
    assert store.list()[0]["league_id"] == "abc-123"
