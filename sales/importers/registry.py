"""Pluggable importer registry.

Architecture
------------
Every POS report format is handled by one :class:`BaseImporter` subclass (see
``base.py``) implementing ``normalize(path) -> list[CanonicalSale]``. A subclass
declares the file extension it handles with the ``@register(".ext")`` decorator
below; ``get_importer_for(path)`` then dispatches by extension and returns the
matching importer instance. Parsing is per-format, but persistence is shared by
all importers and lives in ``persistence.py``.

Adding a new format is a single new file: drop a module in this package with a
``@register``-decorated ``BaseImporter`` subclass. ``autodiscover()`` (called
from the package ``__init__``) imports every submodule on startup, so the
decorator runs without editing any existing code.
"""
import importlib
import pkgutil
from pathlib import Path

from .base import BaseImporter

_REGISTRY: dict[str, type[BaseImporter]] = {}


def register(extension: str):
    """Decorator: register an importer class for a file extension (e.g., '.xlsx')."""
    ext = extension.lower()

    def _wrap(cls: type[BaseImporter]) -> type[BaseImporter]:
        _REGISTRY[ext] = cls
        return cls

    return _wrap


def get_importer_for(path: Path) -> BaseImporter:
    """Return an instance of the importer that handles the file's extension."""
    ext = path.suffix.lower()
    cls = _REGISTRY.get(ext)
    if cls is None:
        raise ValueError(
            f"No importer registered for extension '{ext}'. "
            f"Registered: {list(_REGISTRY)}"
        )
    return cls()


def autodiscover(package_name: str, package_path) -> None:
    """Import every submodule of a package so each ``@register`` decorator runs.

    Importing an already-loaded module is a no-op, so this is safe to call once
    on package import. Any new importer module is picked up automatically.
    """
    for module in pkgutil.iter_modules(package_path):
        importlib.import_module(f"{package_name}.{module.name}")
