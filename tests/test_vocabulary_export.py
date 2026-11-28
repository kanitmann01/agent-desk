"""The SPA's vocabulary module is generated, and the committed copy is current.

The exporter renders nexuusbot.plugins.vocabulary into the TypeScript module
the frontend imports. Re-running it into a temporary path and comparing bytes
with the committed file is the same gate the committed SPA bundle uses: editing
the Python owner without regenerating the module fails here instead of
shipping two vocabularies.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_plugin_vocabulary.py"
COMMITTED = ROOT / "frontend" / "src" / "plugins" / "vocabulary.generated.ts"


def _load_exporter():
    spec = importlib.util.spec_from_file_location("export_plugin_vocabulary", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_module_is_what_the_exporter_writes(tmp_path):
    out = tmp_path / "vocabulary.generated.ts"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(out)],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out.read_text(encoding="utf-8") == COMMITTED.read_text(encoding="utf-8")


def test_the_exporter_writes_every_kind_and_cap():
    exporter = _load_exporter()
    text = exporter.render_typescript()
    for kind in exporter.vocabulary.ELEMENT_KINDS:
        assert f'  "{kind}",' in text
    assert str(exporter.vocabulary.SPARKLINE_MIN_POINTS) in text
    assert str(exporter.vocabulary.SPARKLINE_MAX_POINTS) in text
    assert str(exporter.vocabulary.SAMPLE_MAX_BYTES) in text
    for kind, cap in exporter.vocabulary.ROW_CAPS.items():
        assert f"{kind}: {cap}" in text
