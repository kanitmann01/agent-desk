"""Per-user plugin configuration and the read grant that enforces it.

The signed manifest names the job. The path, the columns, and any goal
live here, under the plugin data directory, and only after the user
confirms them. A read of any other file is refused.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

MAX_INSTANCE_CAP = 6
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SUFFIXES = {".xlsx", ".xlsm", ".csv", ".json"}


class ConfigError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _safe(value: str, what: str) -> str:
    if not isinstance(value, str) or not _SAFE.match(value) or ".." in value:
        raise ConfigError("config:unsafe-name", f"{what} is not a safe name.")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class InstanceStore:
    """One plugin's instances. ``root`` is that plugin's data directory."""

    def __init__(self, root: Path, workspace: Path, cap: int = MAX_INSTANCE_CAP) -> None:
        self.root = Path(root)
        self.workspace = Path(workspace).resolve()
        try:
            number = int(cap)
        except (TypeError, ValueError):
            number = MAX_INSTANCE_CAP
        self.cap = max(1, min(MAX_INSTANCE_CAP, number))

    def _instance_dir(self, plugin_id: str, instance_id: str) -> Path:
        return self.root / _safe(plugin_id, "plugin id") / "instances" / _safe(instance_id, "instance id")

    def _config_path(self, plugin_id: str, instance_id: str) -> Path:
        return self._instance_dir(plugin_id, instance_id) / "config.json"

    def _grant_path(self, plugin_id: str, instance_id: str) -> Path:
        return self._instance_dir(plugin_id, instance_id) / "grant.json"

    def list(self, plugin_id: str) -> list[dict]:
        folder = self.root / _safe(plugin_id, "plugin id") / "instances"
        if not folder.is_dir():
            return []
        found = []
        for child in sorted(folder.iterdir()):
            document = child / "config.json"
            if document.is_file():
                found.append(json.loads(document.read_text(encoding="utf-8")))
        return found

    def read(self, plugin_id: str, instance_id: str) -> dict:
        path = self._config_path(plugin_id, instance_id)
        if not path.is_file():
            raise ConfigError("config:missing", "That instance has no config yet.")
        return json.loads(path.read_text(encoding="utf-8"))

    def create(self, plugin_id: str, instance_id: str, name: str, *, good: str = "up") -> dict:
        if len(self.list(plugin_id)) >= self.cap:
            raise ConfigError(
                "config:cap",
                f"This plugin already has {self.cap} instances.",
            )
        folder = self._instance_dir(plugin_id, instance_id)
        if (folder / "config.json").exists():
            raise ConfigError("config:exists", "That instance already exists.")
        folder.mkdir(parents=True, exist_ok=True)
        document = {
            "schemaVersion": 1,
            "instanceId": instance_id,
            "name": str(name or instance_id),
            "source": None,
            "tracking": {"good": "down" if good == "down" else "up"},
            "confirmedAt": None,
            "suggested": False,
        }
        self._write(folder / "config.json", document)
        return document

    def stage_file(self, plugin_id: str, instance_id: str, path) -> dict:
        candidate = Path(path).expanduser().resolve()
        if not candidate.is_file():
            raise ConfigError("config:missing-file", f"That file does not exist: {candidate}")
        if candidate.suffix.lower() not in _SUFFIXES:
            raise ConfigError(
                "config:unsupported",
                "Open an .xlsx, .xlsm, .csv, or .json file.",
            )
        document = self.read(plugin_id, instance_id)
        document["source"] = {
            "kind": "workbook",
            "path": str(candidate),
            "sheet": None,
            "headerRow": 1,
            "range": None,
        }
        document["confirmedAt"] = None
        document["suggested"] = False
        self._write(self._config_path(plugin_id, instance_id), document)
        grant = {"path": str(candidate), "outsideAccepted": False}
        self._write(self._grant_path(plugin_id, instance_id), grant)
        return document

    def accept_outside(self, plugin_id: str, instance_id: str) -> dict:
        path = self._grant_path(plugin_id, instance_id)
        if not path.is_file():
            raise ConfigError("config:missing", "Stage a file before accepting a path.")
        grant = json.loads(path.read_text(encoding="utf-8"))
        grant["outsideAccepted"] = True
        self._write(path, grant)
        return grant

    def confirm(self, plugin_id: str, instance_id: str, tracking: dict, *, suggested: bool = False) -> dict:
        document = self.read(plugin_id, instance_id)
        source = document.get("source") or {}
        raw = source.get("path")
        if not raw:
            raise ConfigError("config:missing-file", "Open a file before confirming.")
        candidate = Path(raw).resolve()
        self._require_inside_or_accepted(plugin_id, instance_id, candidate)
        clean = _tracking(tracking, document.get("tracking") or {})
        _require_rows_in_file(candidate, source, clean)
        document["tracking"] = clean
        document["confirmedAt"] = _now()
        document["suggested"] = bool(suggested)
        self._write(self._config_path(plugin_id, instance_id), document)
        return document

    def assert_can_read(self, plugin_id: str, instance_id: str, path) -> Path:
        document = self.read(plugin_id, instance_id)
        if not document.get("confirmedAt"):
            raise ConfigError("config:not-confirmed", "Confirm the file before it is read.")
        granted = self._granted(plugin_id, instance_id)
        candidate = Path(path).expanduser().resolve()
        if candidate != granted:
            raise ConfigError("config:not-granted", "That file is not the one you confirmed.")
        self._require_inside_or_accepted(plugin_id, instance_id, candidate)
        return candidate

    def granted_file(self, plugin_id: str, instance_id: str) -> Path:
        document = self.read(plugin_id, instance_id)
        if not document.get("confirmedAt"):
            raise ConfigError("config:not-confirmed", "Confirm the file before it is read.")
        return self.assert_can_read(plugin_id, instance_id, document["source"]["path"])

    def _granted(self, plugin_id: str, instance_id: str) -> Path:
        path = self._grant_path(plugin_id, instance_id)
        if not path.is_file():
            raise ConfigError("config:not-granted", "No file has been granted.")
        grant = json.loads(path.read_text(encoding="utf-8"))
        raw = grant.get("path")
        if not raw:
            raise ConfigError("config:not-granted", "No file has been granted.")
        return Path(raw).resolve()

    def _require_inside_or_accepted(self, plugin_id: str, instance_id: str, candidate: Path) -> None:
        try:
            candidate.resolve().relative_to(self.workspace)
            return
        except ValueError:
            pass
        grant_path = self._grant_path(plugin_id, instance_id)
        accepted = False
        if grant_path.is_file():
            accepted = bool(json.loads(grant_path.read_text(encoding="utf-8")).get("outsideAccepted"))
        if not accepted:
            raise ConfigError(
                "config:outside-workspace",
                "That file is outside the workspace. Accept it before confirming.",
            )

    def _write(self, path: Path, document: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def _require_rows_in_file(candidate: Path, source: dict, clean: dict) -> None:
    """A selection naming rows the staged file does not have means the
    preview went stale underneath the modal: the confirm is refused with
    the existing mismatched-file code, not a new failure shape. The lazy
    import keeps config free of file reading at module load (preview
    imports this module's errors)."""
    rows = clean.get("rows")
    if not isinstance(rows, list) or not rows:
        return
    from agentdesk.plugins.preview import preview_table
    table = preview_table(
        candidate,
        sheet=source.get("sheet"),
        header_row=int(source.get("headerRow") or 1),
        range_text=source.get("range"),
        limit=1_000_000,
    )
    highest = max(row for row in rows if isinstance(row, int))
    if highest >= len(table["rows"]):
        raise ConfigError(
            "config:not-granted",
            "That selection names rows the file does not have. Open the file again.",
        )


def _tracking(incoming: dict, previous: dict) -> dict:
    if not isinstance(incoming, dict):
        raise ConfigError("config:bad-tracking", "The column choice is missing.")
    label = str(incoming.get("labelColumn") or "").strip()
    value = str(incoming.get("valueColumn") or "").strip()
    if not label or not value:
        raise ConfigError("config:bad-tracking", "Pick a label column and a value column.")
    aggregate = str(incoming.get("aggregate") or "sum").lower()
    if aggregate not in ("sum", "count", "latest", "min", "max"):
        raise ConfigError("config:bad-tracking", "Aggregate must be sum, count, latest, min, or max.")
    good = incoming.get("good") or previous.get("good") or "up"
    rows = incoming.get("rows")
    if rows is not None and not (
            isinstance(rows, list) and all(isinstance(item, int) and item >= 0 for item in rows)):
        raise ConfigError("config:bad-tracking", "Row selection must be a list of row numbers.")
    goal = _goal(incoming.get("goal"))
    unit = str(incoming.get("unit") or (goal or {}).get("unit") or "")
    result = {
        "labelColumn": label,
        "valueColumn": value,
        "dateColumn": incoming.get("dateColumn") or None,
        "aggregate": aggregate,
        "good": "down" if good == "down" else "up",
        "unit": unit,
        "rows": rows,
        "goal": goal,
        "pace": _pace(incoming.get("pace")),
    }
    return result


def _goal(value):
    if not value:
        return None
    if not isinstance(value, dict):
        raise ConfigError("config:bad-tracking", "A goal needs a number.")
    try:
        number = float(value.get("value"))
    except (TypeError, ValueError):
        raise ConfigError("config:bad-tracking", "A goal needs a number.")
    return {
        "value": number,
        "unit": str(value.get("unit") or ""),
        "good": "down" if value.get("good") == "down" else "up",
    }


def _pace(value):
    if not value:
        return None
    if not isinstance(value, dict):
        raise ConfigError("config:bad-tracking", "Pace needs a plan, a period, and the days elapsed.")
    try:
        plan = float(value.get("plan"))
        period = float(value.get("periodDays"))
        elapsed = float(value.get("elapsedDays"))
    except (TypeError, ValueError):
        raise ConfigError("config:bad-tracking", "Pace needs a plan, a period, and the days elapsed.")
    if plan < 0 or period <= 0 or elapsed <= 0:
        raise ConfigError("config:bad-tracking", "Pace needs a plan, a period, and the days elapsed.")
    return {"plan": plan, "periodDays": period, "elapsedDays": elapsed}
