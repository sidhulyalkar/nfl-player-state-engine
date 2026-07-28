# nflverse raw-data directory

Raw source files are intentionally excluded from the repository archive. Recreate the exact 2020–2025 benchmark inputs with:

```bash
python scripts/run_real_benchmark.py --download-only
```

The benchmark script downloads weekly player statistics from the official `nflverse-data` `stats_player` release and schedules from the official `nfldata` repository. It writes a SHA-256 source manifest before feature construction.

Do not edit files in this directory. Treat them as immutable source snapshots.
