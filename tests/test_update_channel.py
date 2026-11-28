"""The update channel: version ordering and honest unreadable answers.

The desk reads only the share path the user set; a missing folder or a bad
manifest is a reported state, never an exception that reaches the page.
"""

import json

import pytest

from nexuusbot.update import channel


def _publish(root, version, *, schema=1, manifest=None):
    """One version folder on the share, with a matching manifest."""
    folder = root / version
    folder.mkdir(parents=True)
    document = manifest if manifest is not None else {
        "schema_version": schema,
        "product": "Nexuus Bot",
        "version": version,
        "files": [],
    }
    (folder / "manifest.json").write_text(json.dumps(document), encoding="utf-8")
    return folder


def test_parse_version():
    """Version strings order numerically, not as text."""
    assert channel.parse_version("0.2.10") == (0, 2, 10)
    assert channel.parse_version("1") == (1,)
    assert channel.parse_version("0.10.0") > channel.parse_version("0.9.9")
    with pytest.raises(ValueError):
        channel.parse_version("0.2.beta")


def test_newest_version_selection(tmp_path):
    """The highest version above the running one wins."""
    _publish(tmp_path, "0.1.0")
    _publish(tmp_path, "0.2.0")
    _publish(tmp_path, "0.10.0")
    available = channel.newest(tmp_path, "0.1.0")
    assert available is not None
    assert available.version == "0.10.0"
    assert available.folder == tmp_path / "0.10.0"
    assert available.manifest["version"] == "0.10.0"
    assert channel.newest(tmp_path, "0.10.0") is None


def test_channel_unreadable_reports(tmp_path):
    """Every unreadable share has a plain cause, never a traceback."""
    with pytest.raises(channel.ChannelUnreadable) as missing:
        channel.newest(tmp_path / "gone", "0.1.0")
    assert "folder" in str(missing.value)

    broken = tmp_path / "share"
    _publish(broken, "0.2.0")
    (broken / "0.2.0" / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(channel.ChannelUnreadable) as bad:
        channel.newest(broken, "0.1.0")
    assert "manifest" in str(bad.value)

    old = tmp_path / "old"
    _publish(old, "0.2.0", schema=9)
    with pytest.raises(channel.ChannelUnreadable) as schema:
        channel.newest(old, "0.1.0")
    assert "version 1" in str(schema.value)


def test_a_folder_without_a_manifest_is_ignored(tmp_path):
    """Half-written or scratch folders do not stop the share from working."""
    (tmp_path / "0.5.0").mkdir()
    _publish(tmp_path, "0.2.0")
    assert channel.newest(tmp_path, "0.1.0").version == "0.2.0"
