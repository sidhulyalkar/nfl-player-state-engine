from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_table(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix in {".csv", ".gz"} or path.name.endswith(".csv.gz"):
        return pd.read_csv(path)
    raise ValueError(f"Unsupported table format: {path}")


def write_table(frame: pd.DataFrame, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        frame.to_parquet(path, index=False)
    elif suffix == ".csv":
        frame.to_csv(path, index=False)
    else:
        raise ValueError(f"Unsupported table format: {path}")
    return path


def existing_table(base: str | Path) -> Path:
    base = Path(base)
    candidates = [base, base.with_suffix(".parquet"), base.with_suffix(".csv")]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No table found for {base}")
