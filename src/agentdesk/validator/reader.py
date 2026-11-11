"""Read plugin files relative to a plugin root (directory or zip)."""

import zipfile
from pathlib import Path

MANIFEST_NAME = "manifest.json"


class ValidatorIOError(Exception):
    """The input path cannot be read at all (usage/IO error, CLI exit 2)."""


class DirectoryReader:
    """Reads files relative to a plugin directory on disk."""

    def __init__(self, root: Path):
        self.root = root

    def read_bytes(self, relpath: str):
        """Return the file's bytes, or None when it is absent or escapes root."""
        path = self.root / Path(relpath)
        if ".." in path.parts or not path.is_file():
            return None
        return path.read_bytes()

    def exists(self, relpath: str) -> bool:
        path = self.root / Path(relpath)
        return ".." not in path.parts and path.is_file()


class ZipReader:
    """Reads files from a plugin zip with the manifest at the zip root."""

    def __init__(self, zip_path: Path):
        try:
            self._zip = zipfile.ZipFile(zip_path)
        except (OSError, zipfile.BadZipFile) as exc:
            raise ValidatorIOError(f"cannot read zip: {exc}") from exc

    def read_bytes(self, relpath: str):
        if ".." in Path(relpath).parts:
            return None
        try:
            return self._zip.read(Path(relpath).as_posix())
        except KeyError:
            return None

    def exists(self, relpath: str) -> bool:
        return self.read_bytes(relpath) is not None
