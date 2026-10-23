"""wikibase-cache: read Wikibase instances cache-first and keep every revision seen."""
from __future__ import annotations

__version__ = "0.1.0"


def open_store(target: str):
    """The local store of a configured target, for reading: open_store("mywiki").get("Q5"). No network access."""
    from .config import load
    from .store import Store

    config = load()
    return Store(config.target_dir(target), config.machine_id)
