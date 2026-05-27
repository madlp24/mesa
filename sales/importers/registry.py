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
