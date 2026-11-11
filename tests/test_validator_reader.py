"""Reader behavior: DirectoryReader containment and ZipReader error mapping."""

from .test_validator_support import write_plugin
from agentdesk.validator.reader import DirectoryReader


def test_directory_reader_rejects_dotdot_escape(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside bytes")
    reader = DirectoryReader(write_plugin(tmp_path / "plugin"))

    assert reader.read_bytes("../outside.txt") is None
    assert not reader.exists("../outside.txt")


def test_directory_reader_rejects_absolute_relpath(tmp_path):
    """An absolute relpath would replace the root entirely on join."""
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside bytes")
    reader = DirectoryReader(write_plugin(tmp_path / "plugin"))

    assert reader.read_bytes(str(outside)) is None
    assert not reader.exists(str(outside))
    assert reader.read_bytes(str(outside)) != b"outside bytes"


def test_directory_reader_still_reads_inside_files(tmp_path):
    reader = DirectoryReader(write_plugin(tmp_path / "plugin"))

    assert reader.exists("manifest.json")
    assert reader.read_bytes("manifest.json") is not None
