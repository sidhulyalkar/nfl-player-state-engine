# Contributing

1. Create a focused branch.
2. Add or update tests.
3. Preserve temporal causality in every feature.
4. Run `pytest` and `ruff check src tests`.
5. Document source provenance and licenses for new data.
6. Include an ablation or baseline comparison for model changes.

Features that use information unavailable at prediction time will not be merged, no matter how dazzling the retrospective metric appears.
