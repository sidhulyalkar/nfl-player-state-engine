from player_state_engine.product.demo import seed_product_demo
from player_state_engine.product.store import LeagueSnapshotStore


def test_seed_product_demo(tmp_path):
    paths = seed_product_demo(tmp_path)
    assert all(path.exists() for path in paths.values())
    snapshot = LeagueSnapshotStore(tmp_path / "data/product/leagues").load("demo-league")
    assert len(snapshot.rosters) == 4
    assert len(snapshot.free_agents) == 8
