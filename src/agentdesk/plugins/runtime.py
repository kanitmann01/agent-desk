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

from agentdesk.plugins.execute import PluginWidgetRunner
from agentdesk.validator.core import validate_plugin

PILOT_VIEWS = 3

# Plugin ids and versions become filesystem fragments (install dirs,
# data dirs, rmtree targets), so they are names, not free text.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _alias_id(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip().lower()).strip("-")
    return cleaned or "instance"


def _format_number(value) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}"


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


def extract_plugin_zip(zip_path: Path, destination: Path) -> None:
    """Extract member by member. Python's zipfile has no extraction
    filter, so containment is enforced here: every resolved target must
    stay inside ``destination``. The one extractor for every zip this
    app opens (installs, updates, peer bundles); a refusal raises
    PluginError with ``install:unsafe-zip``."""
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


def _scope_block(manifest: dict) -> dict:
    """Both permission blocks; base leaves keep their historical labels."""
    block: dict = {}
    base = manifest.get("permissions")
    if isinstance(base, dict):
        block.update(base)
    optional = manifest.get("optionalPermissions")
    if isinstance(optional, dict):
        block["optionalPermissions"] = optional
    return block


class PluginRuntime:
    """Owns the installed plugin set: the lockfile is its source of truth."""

    def __init__(self, plugins_dir: Path, data_dir: Path, workspace_dir: Path,
                 now: str | None = None,
                 runner: PluginWidgetRunner | None = None) -> None:
        self.plugins_dir = Path(plugins_dir)
        self.data_dir = Path(data_dir)
        self.workspace_dir = Path(workspace_dir)
        self.now = now or datetime.now().isoformat(timespec="seconds")
        self.runner = runner if runner is not None else PluginWidgetRunner(workspace_dir)
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

    def _verify_installed(self, entry: dict) -> None:
        """Fail closed when installed files no longer match their pin.

        The lockfile records the digest computed at install time; anything
        that edits the active version directory afterwards must not render,
        re-test, or report source status. A missing directory hashes to the
        empty tree and therefore also fails this check.
        """
        version_dir = self._active_version_dir(entry)
        expected = ""
        active = entry.get("active_version")
        for version in entry.get("versions", []):
            if version.get("version") == active:
                expected = version.get("sha256", "")
                break
        else:
            if entry.get("versions"):
                expected = entry["versions"][-1].get("sha256", "")
        if not expected or _tree_digest(version_dir) != expected:
            raise PluginError(
                "plugin:tampered",
                f"installed files changed after install: {entry.get('id', '')}",
                409,
            )

    def _attach_runner(self, plugin_id: str, entry: dict) -> dict:
        """Run the plugin's declared data source through the widget runner.

        The runner returns probe-shaped status (fresh/attention with a
        cause) whether it executed the source or honestly could not; a
        runner failure falls back to the probe so an install never fails
        on the widget half alone.
        """
        version_dir = self._active_version_dir(entry)
        manifest: dict = {}
        try:
            manifest = json.loads((version_dir / "manifest.json").read_text(
                encoding="utf-8"))
            return self.runner.attach(plugin_id, manifest, version_dir,
                                      Path(entry["data_dir"]))
        except Exception:  # noqa: BLE001 - the probe is the honest fallback
            return self.probe(plugin_id, manifest)

    # ---- lifecycle ----

    def install(self, plugin_path: Path, source: str = "zip") -> dict:
        """Install a plugin from a zip or an already-verified directory.

        Directory sources are the registry path: the registry machinery
        resolves the pin, verifies the tree digest and runs the shared
        validator before staging; everything after validation is the
        same for both shapes.
        """
        plugin_path = Path(plugin_path)
        try:
            verdict = validate_plugin(plugin_path)
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
            if plugin_path.is_dir():
                shutil.copytree(plugin_path, staged)
            else:
                extract_plugin_zip(plugin_path, staged)
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
        }
        entry["data_source"] = self._attach_runner(plugin_id, entry)
        state["plugins"][plugin_id] = entry
        self._write(state)
        self._materialize_alias(manifest)
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
            extract_plugin_zip(Path(zip_path), staged)
            manifest = json.loads((staged / "manifest.json").read_text(encoding="utf-8"))
            version = str(manifest["version"])
            digest = _tree_digest(staged)
            # Optional permissions are capability reach too: a release that
            # adds a network host or a new optional file scope must be held for
            # re-consent exactly like a base permission widening.
            added = scope_diff(_scope_block(current_manifest),
                               _scope_block(manifest))
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
        entry["data_source"] = self._attach_runner(plugin_id, entry)
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
        entry["data_source"] = self._attach_runner(plugin_id, entry)
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

    def decline_pending(self, plugin_id: str) -> dict:
        """Drop a held update and its staged tree, a public operation."""
        state = self._read()
        entry = self._entry(state, plugin_id)
        pending = entry.get("pending_update")
        if not pending:
            raise PluginError("consent:nothing-pending",
                              f"{plugin_id} has no update held for consent", 404)
        staged = Path(pending.get("dir") or "")
        try:
            if staged.is_dir():
                shutil.rmtree(staged)
        except OSError:
            pass
        entry["pending_update"] = None
        self._write(state)
        return {"id": plugin_id, "version": pending.get("version", ""),
                "status": "rejected"}

    def rollback(self, plugin_id: str, to_version: str | None = None) -> dict:
        state = self._read()
        entry = self._entry(state, plugin_id)
        versions = entry["versions"]
        names = [v["version"] for v in versions]
        if entry["active_version"] not in names:
            raise PluginError("rollback:unknown-active",
                              f"{plugin_id} active version is not recorded", 409)
        index = names.index(entry["active_version"])
        if to_version:
            if to_version not in names:
                raise PluginError("rollback:unknown-version",
                                  f"{plugin_id} has no recorded version {to_version}",
                                  409)
            target = names.index(to_version)
            if target >= index:
                raise PluginError(
                    "rollback:not-prior",
                    f"{to_version} is not older than the active version", 409)
            previous = versions[target]
        else:
            if index == 0:
                raise PluginError("rollback:no-prior",
                                  f"{plugin_id} has no prior version", 409)
            previous = versions[index - 1]
        entry["active_version"] = previous["version"]
        entry["sha256"] = previous["sha256"]
        entry["data_source"] = self._attach_runner(plugin_id, entry)
        self._write(state)
        return {"rolled_back_to": previous["version"]}

    def enable(self, plugin_id: str) -> dict:
        result = self._set_state(plugin_id, "enabled")
        state = self._read()
        entry = self._entry(state, plugin_id)
        entry["data_source"] = self._attach_runner(plugin_id, entry)
        self._write(state)
        return result

    def disable(self, plugin_id: str) -> dict:
        # A disabled plugin stops touching its declared files: the
        # runner detaches, which stops polling and closes the store.
        self.runner.detach(plugin_id)
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
        self.runner.detach(plugin_id)
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
        self._verify_installed(entry)
        if self.runner.attached(plugin_id):
            entry["data_source"] = self.runner.retest(plugin_id)
        elif entry.get("state") == "enabled":
            # The amber card's own recovery path: an install that found
            # no workbook left the source unattached, and the file may
            # have landed since. Re-test retries the attachment, so the
            # card binds real values instead of only file presence;
            # attach's probe-shaped status answers the still-missing
            # case exactly as the probe did.
            entry["data_source"] = self._attach_runner(plugin_id, entry)
        else:
            # A disabled or uninstalled plugin never (re)attaches: its
            # re-test only refreshes the honest probe line.
            entry["data_source"] = self.probe(plugin_id)
        self._write(state)
        return dict(entry["data_source"])

    def source_status(self, plugin_id: str) -> dict:
        state = self._read()
        entry = self._entry(state, plugin_id)
        self._verify_installed(entry)
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

    def version_dir(self, plugin_id: str) -> Path:
        """The directory of the active version: what publish republishes."""
        entry = self._entry(self._read(), plugin_id)
        return self._active_version_dir(entry)

    def list_records(self) -> list[dict]:
        return [dict(entry) for entry in self._read()["plugins"].values()]

    def layout_keys(self) -> list[str]:
        """Card keys for the dashboard layout.

        A workbook plugin with instances contributes one key per instance.
        An alias contributes none: its instance is a card of the target.
        """
        keys = []
        tracker_done = False
        for entry in self.list_records():
            if entry.get("state") != "enabled" or not entry.get("versions"):
                continue
            manifest = self._manifest(entry["id"])
            config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
            if config.get("aliasOf") or self._is_tracker(manifest):
                if not tracker_done:
                    keys.extend(self._tracker_keys())
                    tracker_done = True
                continue
            keys.append(entry["id"])
        return keys

    def _is_tracker(self, manifest: dict) -> bool:
        config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
        return "workbook" in (config.get("kinds") or []) and not config.get("aliasOf")

    def _tracker_keys(self) -> list[str]:
        from agentdesk.plugins.config import InstanceStore
        instances = InstanceStore(self.data_dir, self.workspace_dir).list("excel-report")
        if not instances:
            return ["excel-report"]
        return [f"excel-report~{item['instanceId']}" for item in instances]

    def _tracker_entry(self, state: dict):
        return state["plugins"].get("excel-report")

    def _tracker_cards(self, entry) -> list[dict]:
        from agentdesk.plugins.config import ConfigError, InstanceStore
        from agentdesk.plugins.tracker import read_tracker
        store = InstanceStore(self.data_dir, self.workspace_dir)
        instances = store.list("excel-report")
        version = "" if not entry else str(entry.get("active_version") or "")
        pilot = bool(entry and entry.get("pilot_views_left", 0) > 0)
        if not instances:
            return [self._tracker_setup_card("main", "Workbook tracker", version, pilot, "source")]
        cards = []
        for item in instances:
            instance_id = item["instanceId"]
            title = str(item.get("name") or instance_id)
            if not item.get("confirmedAt"):
                step = "columns" if (item.get("source") or {}).get("path") else "source"
                cards.append(self._tracker_setup_card(instance_id, title, version, pilot, step))
                continue
            card = self._tracker_setup_card(instance_id, title, version, pilot, "done")
            try:
                reading = read_tracker(store, "excel-report", instance_id)
            except ConfigError as exc:
                card["freshness"] = "attention"
                card["cause"] = exc.message
                card["payload"] = None
                cards.append(card)
                continue
            elements = [
                {"kind": "metric", "label": "Value", "value": _format_number(reading["value"])},
                {"kind": "delta", "label": "Change", "value": reading["delta"],
                 "direction": reading["direction"]},
                {"kind": "text", "label": "Workbook", "text": reading["file"]},
            ]
            if reading.get("paceNote"):
                elements.append({"kind": "text", "label": "Pace", "text": reading["paceNote"]})
            if len(reading.get("points") or []) >= 2:
                elements.append({"kind": "sparkline", "label": "History", "points": reading["points"]})
            card["freshness"] = "fresh"
            card["cause"] = ""
            card["payload"] = {"elements": elements, "status": "fresh"}
            cards.append(card)
        return cards

    def _tracker_setup_card(self, instance_id: str, title: str, version: str,
                            pilot: bool, step: str) -> dict:
        card_id = "excel-report" if instance_id == "main" and step != "done" else f"excel-report~{instance_id}"
        if instance_id == "main" and step == "source":
            card_id = "excel-report"
        return {
            "id": card_id,
            "title": title,
            "version": version,
            "pilot": pilot,
            "state": "enabled",
            "freshness": "setup",
            "cause": "",
            "checked_at": "",
            "pluginId": "excel-report",
            "instanceId": instance_id,
            "payload": {
                "elements": [],
                "setup": {
                    "pluginId": "excel-report",
                    "instanceId": instance_id,
                    "name": title,
                    "step": step,
                },
            },
        }

    def _materialize_alias(self, manifest: dict) -> None:
        config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
        target = config.get("aliasOf")
        if not isinstance(target, str) or not target:
            return
        from agentdesk.plugins.config import ConfigError, InstanceStore
        instance_id = _alias_id(str(config.get("instanceName") or manifest.get("id") or "instance"))
        store = InstanceStore(self.data_dir, self.workspace_dir)
        try:
            store.create(
                target, instance_id, str(config.get("instanceName") or instance_id),
                good="down" if config.get("good") == "down" else "up",
            )
        except ConfigError as exc:
            if exc.code != "config:exists":
                raise

    def widget_cards(self) -> list[dict]:
        """Widget card data for enabled, installed plugins, pilot and amber
        included. One dashboard view spends one pilot view per plugin.

        An attached data source is read live (stale marking included);
        the ui-schema render model rides along as ``payload`` for views
        that can draw it.
        """
        state = self._read()
        cards = []
        dirty = False
        tracker_emitted = False
        for entry in state["plugins"].values():
            if entry["state"] != "enabled" or not entry["versions"]:
                continue
            manifest = {}
            manifest_path = self._active_version_dir(entry) / "manifest.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
            if config.get("aliasOf") or self._is_tracker(manifest):
                if not tracker_emitted:
                    cards.extend(self._tracker_cards(entry if self._is_tracker(manifest) else self._tracker_entry(state)))
                    tracker_emitted = True
                if entry["pilot_views_left"] > 0:
                    entry["pilot_views_left"] -= 1
                    dirty = True
                continue
            if self.runner.attached(entry["id"]):
                # One source read for both halves of the card (#75
                # review): status and payload come from a single
                # status+bindings pass, so a pipeline-backed source (the
                # mail folder included) is read once per view.
                card = self.runner.card(entry["id"])
                data, payload = card["status"], card["payload"]
            else:
                data = entry.get("data_source") or {}
                payload = None
            cards.append({
                "id": entry["id"],
                "title": entry.get("name", entry["id"]),
                "version": entry["active_version"],
                "pilot": entry["pilot_views_left"] > 0,
                "state": entry["state"],
                "freshness": data.get("status", "attention"),
                "cause": data.get("cause", ""),
                "checked_at": data.get("checked_at", ""),
                "manifest": manifest,
                "payload": payload,
            })
            if entry["pilot_views_left"] > 0:
                entry["pilot_views_left"] -= 1
                dirty = True
        if dirty:
            self._write(state)
        return cards

    def widget_payload(self, plugin_id: str) -> dict | None:
        """The bound ui-schema render model for one plugin, or None."""
        entry = self._entry(self._read(), plugin_id)
        self._verify_installed(entry)
        return self.runner.payload(plugin_id) if self.runner.attached(plugin_id) else None

    def start_widget_polls(self) -> None:
        """Resume hourly polling for every attached data source."""
        self.runner.start_all_polling()
