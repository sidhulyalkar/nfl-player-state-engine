"""NFL Player State Engine."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("nfl-player-state-engine")
except PackageNotFoundError:  # pragma: no cover - source tree before editable/install metadata exists
    __version__ = "0+unknown"
