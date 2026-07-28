from player_state_engine.config import load_config


def test_load_config() -> None:
    config = load_config("configs/base.yaml", project_root=".")
    assert 0.5 in config.model.quantiles
    assert config.features.rolling_windows == (3, 5, 8)
