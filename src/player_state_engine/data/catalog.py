from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path


def create_duckdb_catalog(database: str | Path, tables: Mapping[str, str | Path]) -> Path:
    """Create durable DuckDB views over local CSV/Parquet assets."""
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("duckdb is required to create the local catalog.") from exc

    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database))
    try:
        for name, raw_path in tables.items():
            path = Path(raw_path).resolve()
            safe_name = "".join(char if char.isalnum() or char == "_" else "_" for char in name)
            path_sql = str(path).replace("'", "''")
            if path.suffix.lower() == ".parquet":
                reader = f"read_parquet('{path_sql}')"
            elif path.suffix.lower() == ".csv":
                reader = f"read_csv_auto('{path_sql}', header=true)"
            else:
                continue
            connection.execute(f"CREATE OR REPLACE VIEW {safe_name} AS SELECT * FROM {reader}")
    finally:
        connection.close()
    return database
