"""Read plugin files relative to a plugin root (directory or zip)."""

import zipfile
from pathlib import Path

MANIFEST_NAME = "manifest.json"


class ValidatorIOError(Exception):
    """The input path cannot be read at all (usage/IO error, CLI exit 2)."""


class DirectoryReader:
    """Reads files relative to a plugin directory on disk."""

    def __init__(self, root: Path):
        """Hold the directory that plugin files are read from."""
        self.root = root

    def read_bytes(self, relpath: str):
        """Return the file's bytes, or None when it is absent or escapes root."""
        path = self._contained_path(relpath)
        if path is None or not path.is_file():
            return None
        return path.read_bytes()

    def exists(self, relpath: str) -> bool:
        """Whether the plugin tree contains this file.

        A path that resolves outside the root counts as absent rather than
        raising.
        """
        path = self._contained_path(relpath)
        return path is not None and path.is_file()

    def _contained_path(self, relpath: str):
        """Join ``relpath`` under root, or None when it would escape root.

        An absolute relpath replaces the root entirely on join, and a symlink
        could still point outside, so containment is verified on the resolved
        path as well.
        """
        rel = Path(relpath)
        path = self.root / rel
        if rel.is_absolute() or ".." in path.parts:
            return None
        if not path.resolve().is_relative_to(self.root.resolve()):
            return None
        return path


class ZipReader:
    """Reads files from a plugin zip with the manifest at the zip root."""

    def __init__(self, zip_path: Path):
        """Open the archive once for the lifetime of the reader.

        Raises ValidatorIOError when the file cannot be opened or is not a zip,
        so a caller never holds a reader that cannot answer.
        """
        try:
            self._zip = zipfile.ZipFile(zip_path)
        except (OSError, zipfile.BadZipFile) as exc:
            raise ValidatorIOError(f"cannot read zip: {exc}") from exc

    def read_bytes(self, relpath: str):
        """Return the entry's bytes, or None when the archive has no such entry.

        A path carrying .. is refused before the archive is touched; a corrupt
        entry raises ValidatorIOError instead of reading as absent.
        """
        if ".." in Path(relpath).parts:
            return None
        try:
            return self._zip.read(Path(relpath).as_posix())
        except KeyError:
            return None
        except (RuntimeError, zipfile.BadZipFile, OSError) as exc:
            raise ValidatorIOError(f"cannot read zip entry: {exc}") from exc

    def exists(self, relpath: str) -> bool:
        """Whether the archive contains this entry."""
        return self.read_bytes(relpath) is not None
