# README images

These files support the root `README.md`.

- `dashboard.png`: sample-data morning dashboard.
- `memory.png`: memory page or graph view.
- `marketplace.png`: marketplace Discover or plugin Detail view.
- `architecture.svg`: original Nexuus Bot architecture diagram.
- `badges/`: Shields.io SVGs for Python, React, loopback networking, and the proprietary license. The files are stored locally to avoid third-party requests.

## Source

- Repository: `kanitmann01/agent-desk`
- Source commit: `37515e9643c60857263c65b376e8c54f51dcc04a`
- Capture date: 2026-11-25
- Theme: Unkey
- Viewport: 1280×800

## Capture command

On a clean machine, install the browser first. The audit drives Chromium through Playwright, and Playwright downloads no browser by itself:

```bash
uv run --no-project --with playwright playwright install chromium
```

Then capture:

```bash
uv run --no-project --with playwright --with keyring --with cryptography \
  python tools/layout_audit.py \
  --conditions fresh,data \
  --widths 1280 \
  --themes unkey \
  --routes "dashboard,marketplace,memory" \
  --no-stress \
  --fail-on none \
  --out build/readme-shots
```

The audit uses synthetic data, a fake keychain, a loopback mock model, fixed clocks, and a temporary data folder. It does not read the user's application data folder.

## Replacement note

The screenshots show the current UI without edits. The product UI is changing in a separate task. Replace these PNG files in place when that work lands. Keep the same filenames so the root README does not need link changes.

The audit writes each full-page screenshot under `build/readme-shots/<condition>/<width>x<height>/<theme>/<route>__<state>.png`. The three README images come from the `data` condition, the sample-data desk. Copy these produced files over the committed images, keeping the filenames:

- `build/readme-shots/data/1280x800/unkey/root__dashboard.png` over `docs/readme/dashboard.png`
- `build/readme-shots/data/1280x800/unkey/memory__memory.png` over `docs/readme/memory.png`
- `build/readme-shots/data/1280x800/unkey/marketplace__marketplace.png` over `docs/readme/marketplace.png`

Do not use the `long-values` audit condition for public images. Its fixture contains a real local username and path.
