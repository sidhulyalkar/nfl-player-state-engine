.PHONY: install dev test lint smoke benchmark-smoke clean

install:
	python -m pip install -e .

dev:
	python -m pip install -e '.[dev,dashboard,intelligence]'

test:
	pytest

lint:
	ruff check src tests

smoke:
	pse smoke-test --work-dir .smoke

benchmark-smoke:
	pse make-synthetic --output-dir .benchmark-smoke/raw --season 2022 --season 2023 --weeks 12
	pse build-features --stats .benchmark-smoke/raw/player_stats.csv --schedules .benchmark-smoke/raw/schedules.csv --output .benchmark-smoke/features.parquet
	pse benchmark-multiseason --features .benchmark-smoke/features.parquet --target fantasy_points_ppr --min-train-weeks 8 --retrain-every 4 --output-dir .benchmark-smoke/report

clean:
	rm -rf .smoke .pytest_cache .ruff_cache .mypy_cache
