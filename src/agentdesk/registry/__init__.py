"""Internal plugin registry: index, pinned install, and CI review."""
from .index import RegistryIndex, RegistryIndexError, load_index

__all__ = ["RegistryIndex", "RegistryIndexError", "load_index"]
