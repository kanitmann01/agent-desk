"""Reader behavior: DirectoryReader containment and ZipReader error mapping."""

import zipfile

import pytest

from .test_validator_support import fixture, run_cli, write_plugin
from agentdesk.validator import ValidatorIOError
from agentdesk.validator.reader import DirectoryReader, ZipReader


def make_zip(dest, source_dir):
    """Zip a plugin directory with the manifest at the zip root."""
    with zipfile.ZipFile(dest, "w") as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(source_dir).as_posix())
    return dest


def corrupt_first_entry(zip_path):
    """Flip one byte of the first stored entry's data so its CRC breaks."""
    data = bytearray(zip_path.read_bytes())
    start = data.index(b"PK\x03\x04")
    name_len = int.from_bytes(data[start + 26 : start + 28], "little")
    extra_len = int.from_bytes(data[start + 28 : start + 30], "little")
    data[start + 30 + name_len + extra_len] ^= 0xFF
    zip_path.write_bytes(bytes(data))


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


def test_zip_reader_corrupt_entry_raises_validator_io_error(tmp_path):
    zip_path = make_zip(tmp_path / "plugin.zip", fixture("valid-manifest"))
    corrupt_first_entry(zip_path)

    reader = ZipReader(zip_path)

    with pytest.raises(ValidatorIOError):
        reader.read_bytes("manifest.json")


def test_zip_reader_encrypted_entry_raises_validator_io_error(tmp_path):
    zip_path = make_zip(tmp_path / "plugin.zip", fixture("valid-manifest"))
    reader = ZipReader(zip_path)

    def encrypted_read(name, pwd=None):
        raise RuntimeError(f"File {name} is encrypted, password required for extraction")

    reader._zip.read = encrypted_read

    with pytest.raises(ValidatorIOError):
        reader.read_bytes("manifest.json")


def test_zip_reader_missing_entry_is_none(tmp_path):
    reader = ZipReader(make_zip(tmp_path / "plugin.zip", fixture("valid-manifest")))

    assert reader.read_bytes("absent.json") is None


def test_cli_corrupt_zip_entry_is_exit_2_not_traceback(tmp_path):
    zip_path = make_zip(tmp_path / "plugin.zip", fixture("valid-manifest"))
    corrupt_first_entry(zip_path)

    result = run_cli(str(zip_path))

    assert result.returncode == 2
    assert result.stderr.strip()
    assert "Traceback" not in result.stderr
