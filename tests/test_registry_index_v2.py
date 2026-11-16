"""Registry index v2: schema, round-trip, and the v1 compatibility wrapper."""
from __future__ import annotations

import json

import pytest

from agentdesk.registry.index import RegistryIndexError, load_index

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SIG = "s" * 86

V2_INDEX = {
    "schemaVersion": 2,
    "version": 4,
    "generatedAt": "2026-11-15T12:00:00+00:00",
    "publishers": {
        "acme-tools": {
            "keyId": "publisher-2026",
            "provenance": {"kind": "dns", "value": "acme-tools.example"},
        }
    },
    "plugins": [
        {
            "id": "sales-delta-widget",
            "name": "Sales 24h Delta",
            "publisher": "acme-tools",
            "category": "sales",
            "tags": ["demo", "sales"],
            "latest": "1.2.0",
            "risk": "low",
            "class": "declarative",
            "releases": [
                {
                    "version": "1.2.0",
                    "sha256": SHA_A,
                    "digest": SHA_B,
                    "signature": SIG,
                    "tag": "sales-delta-widget-1.2.0",
                    "changelog": "Adds the delta column",
                    "minHost": "0.1.0",
                    "yanked": False,
                },
                {
                    "version": "1.1.0",
                    "sha256": SHA_C,
                    "source": "local",
                    "changelog": "Previous release",
                    "yanked": True,
                },
            ],
        }
    ],
}


def load(document):
    return load_index(json.dumps(document))


def test_v2_round_trips_through_model():
    index = load(V2_INDEX)
    assert index.schema_version == 2
    assert index.plugins[0].name == "Sales 24h Delta"
    assert index.plugins[0].category == "sales"
    assert index.plugins[0].tags == ("demo", "sales")
    assert index.publishers["acme-tools"].key_id == "publisher-2026"
    assert index.version == 4
    assert json.loads(index.to_json()) == V2_INDEX


def test_v2_release_signature_and_digest_are_kept():
    index = load(V2_INDEX)
    release = index.plugin("sales-delta-widget").release_for("1.2.0")
    assert release.digest == SHA_B
    assert release.signature == SIG
    assert release.changelog == "Adds the delta column"
    assert release.min_host == "0.1.0"
    assert release.yanked is False


def test_v2_missing_version_counter_defaults_to_zero():
    document = dict(V2_INDEX)
    document.pop("version")
    index = load(document)
    assert index.version == 0
    assert json.loads(index.to_json())["version"] == 0


def test_v2_rejects_unknown_top_level_key():
    document = dict(V2_INDEX)
    document["unexpected"] = True
    with pytest.raises(RegistryIndexError) as excinfo:
        load(document)
    assert "index:unknown-key:unexpected" == excinfo.value.code


def test_v2_rejects_unknown_release_key():
    document = json.loads(json.dumps(V2_INDEX))
    document["plugins"][0]["releases"][0]["surprise"] = 1
    with pytest.raises(RegistryIndexError) as excinfo:
        load(document)
    assert "index:unknown-key:surprise" == excinfo.value.code


def test_v2_rejects_unknown_publisher_key():
    document = json.loads(json.dumps(V2_INDEX))
    document["publishers"]["acme-tools"]["surprise"] = 1
    with pytest.raises(RegistryIndexError) as excinfo:
        load(document)
    assert "index:unknown-key:surprise" == excinfo.value.code


def test_v2_rejects_bad_version_counter():
    document = dict(V2_INDEX)
    document["version"] = -1
    with pytest.raises(RegistryIndexError, match="version"):
        load(document)
    document["version"] = True
    with pytest.raises(RegistryIndexError, match="version"):
        load(document)


def test_v2_release_tag_is_still_safety_checked():
    document = json.loads(json.dumps(V2_INDEX))
    document["plugins"][0]["releases"][0]["tag"] = "../escape"
    with pytest.raises(RegistryIndexError) as excinfo:
        load(document)
    assert excinfo.value.code.startswith("index:unsafe-tag")


def test_v2_bad_source_is_rejected():
    document = json.loads(json.dumps(V2_INDEX))
    document["plugins"][0]["releases"][1]["source"] = "ftp"
    with pytest.raises(RegistryIndexError) as excinfo:
        load(document)
    assert excinfo.value.code == "index:release-source-invalid"


def test_v1_wrapper_keeps_ids_and_releases(tmp_path):
    from registry_fixtures import make_registry

    repo = make_registry(tmp_path)
    raw = (repo / "index.json").read_text(encoding="utf-8")
    index = load_index(raw)
    assert index.schema_version == 2
    assert index.version == 0
    assert index.generated_at == ""
    assert index.publishers == {}
    assert [plugin.id for plugin in index.plugins] == ["sales-delta-widget"]
    releases = index.plugins[0].releases
    assert [(release.version, release.sha256, release.tag) for release in releases] == [
        ("1.2.0", releases[0].sha256, "sales-delta-widget-1.2.0")
    ]


def test_v1_wrapper_emits_v2_json(tmp_path):
    from registry_fixtures import make_registry

    repo = make_registry(tmp_path)
    index = load_index((repo / "index.json").read_text(encoding="utf-8"))
    document = json.loads(index.to_json())
    assert document["schemaVersion"] == 2
    assert document["version"] == 0
    assert document["publishers"] == {}
    assert document["plugins"][0]["id"] == "sales-delta-widget"
    assert document["plugins"][0]["releases"][0]["tag"] == "sales-delta-widget-1.2.0"


def test_v1_wrapper_accepts_legacy_dependencies():
    document = {
        "schemaVersion": 1,
        "plugins": [
            {
                "id": "sales-delta-widget",
                "publisher": "acme-tools",
                "latest": "1.2.0",
                "risk": "low",
                "class": "declarative",
                "dependencies": {"excel-report": ">=0.1.0"},
                "releases": [
                    {
                        "version": "1.2.0",
                        "sha256": SHA_A,
                        "tag": "sales-delta-widget-1.2.0",
                    }
                ],
            }
        ],
    }
    index = load(document)
    assert index.plugins[0].dependencies == {"excel-report": ">=0.1.0"}


def test_unsupported_schema_version_is_named():
    with pytest.raises(RegistryIndexError) as excinfo:
        load({"schemaVersion": 3, "plugins": []})
    assert excinfo.value.code == "index:unsupported-schemaVersion"
