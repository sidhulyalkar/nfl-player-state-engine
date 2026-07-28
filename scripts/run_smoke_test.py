import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from player_state_engine.config import load_config
from player_state_engine.pipelines.workflows import smoke_test_workflow


if __name__ == "__main__":
    artifacts = smoke_test_workflow(Path(".smoke"), load_config())
    for name, path in artifacts.items():
        print(f"{name}: {path}")
