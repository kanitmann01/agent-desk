"""The plugin runtime lifecycle: install, pilot, scopes, rollback, amber.

Every install validates first through the shared ``validate_plugin``:
nothing that fails validation executes or touches disk beyond the
caller's own staging. Installed plugins land in versioned directories
recorded in a lockfile. Updates diff scopes: identical or narrower
applies silently, a widening holds for re-consent with the exact added
scopes. Uninstall keeps plugin data until a separately named purge.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from glob import glob
from pathlib import Path

from agentdesk.validator.core import validate_plugin

PILOT_VIEWS = 3

# Plugin ids and versions become filesystem fragments (install dirs,
# data dirs, rmtree targets), so they are names, not free text.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _require_safe_name(value: str, what: str) -> None:
    if (not value or "/" in value or "\\" in value or value.startswith("-")
            or ".." in value or not _SAFE_NAME.match(value)):
        raise PluginError("plugin:unsafe-name",
                          f"{what} is not a safe name: {value[:40]!r}", 400)


class PluginError(Exception):
    """A named lifecycle refusal: ``code`` is the stable vocabulary."""

    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class ExtractedPlugin:
    dir: Path
    manifest: dict
    sha256: str


def _tree_digest(plugin_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(plugin_dir).rglob("*")):
        if not path.is_file():
            continue
        digest.update(path.relative_to(plugin_dir).as_posix().encode("utf-8") + b"\n")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _extract_zip(zip_path: Path, destination: Path) -> None:
    """Extract member by member. Python's zipfile has no extraction
    filter, so containment is enforced here: every resolved target must
    stay inside ``destination``."""
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = Path(info.filename)
            if name.is_absolute() or ".." in name.parts:
                raise PluginError("install:unsafe-zip",
                                  f"unsafe zip entry: {info.filename}", 400)
            target = destination / name
            if not str(target.resolve()).startswith(str(destination.resolve())):
                raise PluginError("install:unsafe-zip",
                                  f"zip entry escapes the plugin root: {info.filename}",
                                  400)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def scope_items(permissions: dict) -> set[str]:
    """Serialize a permission block into comparable leaf scopes."""
    items: set[str] = set()

    def walk(prefix: str, node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(f"{prefix}.{key}" if prefix else key, value)
        elif isinstance(node, list):
            for value in node:
                walk(prefix, value)
        else:
            items.add(f"{prefix}: {node}")

    walk("", permissions or {})
    return items


def scope_diff(old_permissions: dict, new_permissions: dict) -> list[str]:
    """Scopes the new manifest adds over the old one, sorted."""
    return sorted(scope_items(new_permissions) - scope_items(old_permissions))


class PluginRuntime:
    """Owns the installed plugin set: the lockfile is its source of truth."""

    def __init__(self, plugins_dir: Path, data_dir: Path, workspace_dir: Path,
                 now: str | None = None) -> None:
        self.plugins_dir = Path(plugins_dir)
        self.data_dir = Path(data_dir)
        self.workspace_dir = Path(workspace_dir)
        self.now = now or datetime.now().isoformat(timespec="seconds")
        self._lockfile = self.plugins_dir / "lockfile.json"
        self._staging = self.plugins_dir / ".staging"

    # ---- persistence ----

    def _read(self) -> dict:
        if not self._lockfile.exists():
            return {"plugins": {}, "graveyard": {}}
        return json.loads(self._lockfile.read_text(encoding="utf-8"))

    def _write(self, document: dict) -> None:
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self._lockfile.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _entry(self, state: dict, plugin_id: str) -> dict:
        entry = state["plugins"].get(plugin_id)
        if entry is None:
            raise PluginError("plugin:unknown", f"no installed plugin {plugin_id}", 404)
        return entry

    @staticmethod
    def _active_version_dir(entry: dict) -> Path:
        """The directory of the version the user is actually on: after a
        rollback that is not the newest entry, and re-consent as well as
        rendering must compare against what the user sees."""
        active = entry.get("active_version")
        for version in entry["versions"]:
            if version["version"] == active:
                return Path(version["dir"])
        return Path(entry["versions"][-1]["dir"])

    # ---- lifecycle ----

    def install(self, zip_path: Path, source: str = "zip") -> dict:
        zip_path = Path(zip_path)
        try:
            verdict = validate_plugin(zip_path)
        except PluginError:
            raise
        except Exception as exc:  # unreadable file: a bad request
            raise PluginError("install:unreadable", str(exc), 400)
        if not verdict.ok:
            first = verdict.failures[0]
            raise PluginError("install:validator-failed",
                              f"{first.code}: {first.message}", 400)

        state = self._read()
        self._staging.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self._staging) as tmp:
            staged = Path(tmp) / "plugin"
            _extract_zip(zip_path, staged)
            manifest = json.loads((staged / "manifest.json").read_text(encoding="utf-8"))
            plugin_id = str(manifest["id"])
            version = str(manifest["version"])
            _require_safe_name(plugin_id, "plugin id")
            _require_safe_name(version, "version")
            digest = _tree_digest(staged)
            version_dir = self.plugins_dir / plugin_id / version
            version_dir.parent.mkdir(parents=True, exist_ok=True)
            if version_dir.exists():
                shutil.rmtree(version_dir)
            shutil.move(str(staged), str(version_dir))

        data_dir = self.data_dir / plugin_id
        data_dir.mkdir(parents=True, exist_ok=True)
        schedules = [event for event in manifest.get("activationEvents", [])
                     if event.startswith("onSchedule:")]
        entry = {
            "id": plugin_id,
            "name": str(manifest.get("name", plugin_id)),
            "state": "enabled",
            "active_version": version,
            "source": source,
            "sha256": digest,
            "installed_at": self.now,
            "pilot_views_left": PILOT_VIEWS,
            "versions": [{"version": version, "sha256": digest,
                          "dir": str(version_dir), "installed_at": self.now}],
            "pending_update": None,
            "schedules": schedules,
            "data_dir": str(data_dir),
            "data_source": self.probe(plugin_id, manifest),
        }
        state["plugins"][plugin_id] = entry
        self._write(state)
        return {"ok": True, "id": plugin_id, "version": version,
                "sha256": digest, "pilot": True}

    def update(self, plugin_id: str, zip_path: Path) -> dict:
        state = self._read()
        entry = self._entry(state, plugin_id)
        if entry["state"] == "uninstalled":
            raise PluginError("update:uninstalled",
                              f"{plugin_id} is uninstalled", 409)
        if entry.get("pending_update"):
            raise PluginError("update:already-pending",
                              f"{plugin_id} already holds a re-consent", 409)

        try:
            verdict = validate_plugin(Path(zip_path))
        except PluginError:
            raise
        except Exception as exc:
            raise PluginError("update:unreadable", str(exc), 400)
        if not verdict.ok:
            first = verdict.failures[0]
            raise PluginError("update:validator-failed",
                              f"{first.code}: {first.message}", 400)

        current_manifest = json.loads(
            (self._active_version_dir(entry) / "manifest.json").read_text(encoding="utf-8"))
        self._staging.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self._staging) as tmp:
            staged = Path(tmp) / "plugin"
            _extract_zip(Path(zip_path), staged)
            manifest = json.loads((staged / "manifest.json").read_text(encoding="utf-8"))
            version = str(manifest["version"])
            digest = _tree_digest(staged)
            added = scope_diff(current_manifest.get("permissions", {}),
                               manifest.get("permissions", {}))
            if added:
                pending_dir = self._staging / f"{plugin_id}-{version}"
                if pending_dir.exists():
                    shutil.rmtree(pending_dir)
                shutil.move(str(staged), str(pending_dir))
                entry["pending_update"] = {
                    "version": version, "sha256": digest,
                    "dir": str(pending_dir), "added_scopes": added,
                }
                self._write(state)
                return {"applied": False, "status": "pending-consent",
                        "added_scopes": added}
            version_dir = self.plugins_dir / plugin_id / version
            version_dir.parent.mkdir(parents=True, exist_ok=True)
            if version_dir.exists():
                shutil.rmtree(version_dir)
            shutil.move(str(staged), str(version_dir))

        entry["versions"].append({"version": version, "sha256": digest,
                                  "dir": str(version_dir),
                                  "installed_at": self.now})
        entry["active_version"] = version
        entry["sha256"] = digest
        self._write(state)
        return {"applied": True, "status": "updated", "version": version}

    def consent(self, plugin_id: str) -> dict:
        state = self._read()
        entry = self._entry(state, plugin_id)
        pending = entry.get("pending_update")
        if not pending:
            raise PluginError("consent:nothing-pending",
                              f"{plugin_id} has no update held for consent", 404)
        version_dir = self.plugins_dir / plugin_id / pending["version"]
        version_dir.parent.mkdir(parents=True, exist_ok=True)
        if version_dir.exists():
            shutil.rmtree(version_dir)
        shutil.move(pending["dir"], str(version_dir))
        entry["versions"].append({"version": pending["version"],
                                  "sha256": pending["sha256"],
                                  "dir": str(version_dir),
                                  "installed_at": self.now})
        entry["active_version"] = pending["version"]
        entry["sha256"] = pending["sha256"]
        entry["pending_update"] = None
        self._write(state)
        return {"applied": True, "version": pending["version"]}

    def pending_diff(self, plugin_id: str) -> dict:
        entry = self._entry(self._read(), plugin_id)
        pending = entry.get("pending_update")
        if not pending:
            raise PluginError("consent:nothing-pending",
                              f"{plugin_id} has no update held for consent", 404)
        return {"version": pending["version"],
                "added_scopes": pending["added_scopes"]}

    def rollback(self, plugin_id: str) -> dict:
        state = self._read()
        entry = self._entry(state, plugin_id)
        versions = entry["versions"]
        if entry["active_version"] not in [v["version"] for v in versions]:
            raise PluginError("rollback:unknown-active",
                              f"{plugin_id} active version is not recorded", 409)
        index = [v["version"] for v in versions].index(entry["active_version"])
        if index == 0:
            raise PluginError("rollback:no-prior",
                              f"{plugin_id} has no prior version", 409)
        previous = versions[index - 1]
        entry["active_version"] = previous["version"]
        entry["sha256"] = previous["sha256"]
        self._write(state)
        return {"rolled_back_to": previous["version"]}

    def enable(self, plugin_id: str) -> dict:
        return self._set_state(plugin_id, "enabled")

    def disable(self, plugin_id: str) -> dict:
        return self._set_state(plugin_id, "disabled")

    def _set_state(self, plugin_id: str, state_name: str) -> dict:
        state = self._read()
        entry = self._entry(state, plugin_id)
        entry["state"] = state_name
        self._write(state)
        return {"id": plugin_id, "state": state_name}

    def uninstall(self, plugin_id: str) -> dict:
        state = self._read()
        entry = self._entry(state, plugin_id)
        for version_entry in entry["versions"]:
            version_dir = Path(version_entry["dir"])
            if version_dir.exists():
                shutil.rmtree(version_dir)
        if entry.get("pending_update") and Path(entry["pending_update"]["dir"]).exists():
            shutil.rmtree(entry["pending_update"]["dir"])
        entry["versions"] = []
        entry["pending_update"] = None
        entry["schedules"] = []
        entry["state"] = "uninstalled"
        state["graveyard"][plugin_id] = {"data_dir": entry["data_dir"]}
        self._write(state)
        return {"id": plugin_id, "state": "uninstalled",
                "data_preserved": True, "data_dir": entry["data_dir"]}

    def purge_data(self, plugin_id: str, confirmation: str | None) -> dict:
        expected = f"delete-data:{plugin_id}"
        if confirmation != expected:
            raise PluginError(
                "purge:confirmation-required",
                f"deleting plugin data needs the separate confirmation {expected!r}",
                409)
        state = self._read()
        entry = self._entry(state, plugin_id)
        data_dir = Path(entry["data_dir"])
        if data_dir.exists():
            shutil.rmtree(data_dir)
        state["graveyard"].pop(plugin_id, None)
        del state["plugins"][plugin_id]
        self._write(state)
        return {"purged": plugin_id}

    # ---- observation ----

    def probe(self, plugin_id: str, manifest: dict | None = None) -> dict:
        """Run the plugin's declared data source: file presence, honestly."""
        manifest = manifest or self._manifest(plugin_id)
        widgets = manifest.get("contributes", {}).get("widgets", [])
        if not widgets:
            return {"status": "attention", "cause": "plugin contributes no widget",
                    "checked_at": self.now}
        source = widgets[0].get("dataSource", {})
        pattern = str(source.get("file", "")).replace("${workspace}",
                                                      str(self.workspace_dir))
        if not pattern:
            return {"status": "attention", "cause": "data source has no file",
                    "checked_at": self.now}
        matches = sorted(glob(pattern))
        if matches:
            return {"status": "fresh", "cause": "",
                    "checked_at": self.now, "file": Path(matches[0]).name}
        return {"status": "attention",
                "cause": f"no file matches {source.get('file')}",
                "checked_at": self.now}

    def retest(self, plugin_id: str) -> dict:
        state = self._read()
        entry = self._entry(state, plugin_id)
        entry["data_source"] = self.probe(plugin_id)
        self._write(state)
        return dict(entry["data_source"])

    def source_status(self, plugin_id: str) -> dict:
        state = self._read()
        entry = self._entry(state, plugin_id)
        return dict(entry.get("data_source") or self.probe(plugin_id))

    def _manifest(self, plugin_id: str) -> dict:
        state = self._read()
        entry = self._entry(state, plugin_id)
        manifest_path = (Path(entry["versions"][-1]["dir"]) / "manifest.json") \
            if entry["versions"] else None
        if manifest_path is None or not manifest_path.exists():
            return {}
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def record(self, plugin_id: str) -> dict:
        state = self._read()
        entry = self._entry(state, plugin_id)
        return dict(entry)

    def list_records(self) -> list[dict]:
        return [dict(entry) for entry in self._read()["plugins"].values()]

    def widget_cards(self) -> list[dict]:
        """Widget card data for enabled, installed plugins, pilot and amber
        included. One dashboard view spends one pilot view per plugin."""
        state = self._read()
        cards = []
        dirty = False
        for entry in state["plugins"].values():
            if entry["state"] != "enabled" or not entry["versions"]:
                continue
            manifest = {}
            manifest_path = self._active_version_dir(entry) / "manifest.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            data = entry.get("data_source") or {}
            cards.append({
                "id": entry["id"],
                "title": entry.get("name", entry["id"]),
                "version": entry["active_version"],
                "pilot": entry["pilot_views_left"] > 0,
                "state": entry["state"],
                "freshness": data.get("status", "attention"),
                "cause": data.get("cause", ""),
                "manifest": manifest,
            })
            if entry["pilot_views_left"] > 0:
                entry["pilot_views_left"] -= 1
                dirty = True
        if dirty:
            self._write(state)
        return cards
