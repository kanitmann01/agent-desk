"""The marketplace source must not contain a telemetry/analytics client."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (REPO_ROOT / "src" / "nexuusbot", REPO_ROOT / "frontend" / "src")
SKIP_PARTS = {"static", "spa", "__pycache__", "node_modules", "dist"}
SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".html"}

# Host fragments and SDK names that only a telemetry/analytics integration needs.
TELEMETRY_MARKERS = (
    "sentry.io",
    "sentry_sdk",
    "posthog.com",
    "posthog",
    "segment.io",
    "segment.com",
    "mixpanel.com",
    "mixpanel",
    "amplitude.com",
    "api.amplitude",
    "datadoghq.com",
    "newrelic.com",
    "fullstory.com",
    "hotjar.com",
    "googletagmanager.com",
    "google-analytics.com",
    "plausible.io",
    "matomo.",
)


def test_no_telemetry_hosts_or_sdks_in_source() -> None:
    offenders: list[str] = []
    for scan_root in SCAN_ROOTS:
        assert scan_root.is_dir(), f"missing source root {scan_root}"
        for path in scan_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SUFFIXES:
                continue
            if SKIP_PARTS.intersection(path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            for marker in TELEMETRY_MARKERS:
                if marker in text:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {marker}")
    assert not offenders, "telemetry integration found:\n" + "\n".join(offenders)
