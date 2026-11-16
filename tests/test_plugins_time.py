'''Time and commitments family: discovery, validation and sample rendering.'''

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentdesk.plugins.render import ELEMENT_KINDS, render_sample  # noqa: E402
from agentdesk.validator.core import validate_plugin  # noqa: E402

PLUGINS = ROOT / 'registry' / 'plugins'
FAMILY = (
    'calendar-today',
    'week-load',
    'meeting-prep',
    'follow-up-watch',
    'renewal-radar',
)
CALENDAR_SOURCES = ('calendar-today', 'week-load', 'meeting-prep')
CALENDAR_ICONS = {'calendar', 'clock'}
WATCH_SOURCES = (
    ('follow-up-watch', 'csv-watch', '${workspace}/commitments/*.csv', 'Owner', 'Due'),
    ('renewal-radar', 'excel-watch', '${workspace}/ops/contracts*.xlsx', 'Vendor', 'NoticeDate'),
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _manifest(plugin_id: str) -> dict:
    return _read_json(PLUGINS / plugin_id / 'manifest.json')


def _widget_contribution(plugin_id: str) -> dict:
    return _manifest(plugin_id)['contributes']['widgets'][0]


def _widget(plugin_id: str) -> dict:
    widget = _widget_contribution(plugin_id)
    return _read_json(PLUGINS / plugin_id / widget['render']['file'])


def _sample(plugin_id: str) -> dict:
    return _read_json(PLUGINS / plugin_id / 'sample.json')


def _time_plugin_ids() -> set[str]:
    found = set()
    for path in sorted(PLUGINS.iterdir()):
        if path.is_dir() and (path / 'manifest.json').is_file():
            manifest = _read_json(path / 'manifest.json')
            if manifest.get('category') == 'time':
                found.add(manifest.get('id', path.name))
    return found


def _slot_names(element: dict) -> list[str]:
    return [key for key in element if key == 'binding' or key.endswith('Binding')]


def test_family_discovery_finds_exactly_the_five_time_plugins():
    assert _time_plugin_ids() == set(FAMILY)


@pytest.mark.parametrize('plugin_id', FAMILY)
def test_plugin_passes_the_v2_validator(plugin_id: str):
    verdict = validate_plugin(PLUGINS / plugin_id)
    assert verdict.ok, (plugin_id, verdict.failures)


@pytest.mark.parametrize('plugin_id', FAMILY)
def test_manifest_carries_the_family_metadata(plugin_id: str):
    manifest = _manifest(plugin_id)
    assert manifest['schemaVersion'] == 2
    assert manifest['category'] == 'time'
    assert manifest['class'] == 'declarative'
    assert len(manifest['tags']) == 3
    assert manifest['icon'] in CALENDAR_ICONS
    assert len(manifest['highlights']) == 3
    assert manifest['sample'] == 'sample.json'
    assert (PLUGINS / plugin_id / 'README.md').is_file()


@pytest.mark.parametrize('plugin_id', FAMILY)
def test_widget_elements_use_known_kinds(plugin_id: str):
    elements = _widget(plugin_id)['elements']
    assert elements, plugin_id
    for element in elements:
        assert element['type'] in ELEMENT_KINDS, (plugin_id, element['type'])


@pytest.mark.parametrize('plugin_id', FAMILY)
def test_sample_binds_every_element_slot(plugin_id: str):
    bindings = _sample(plugin_id)['bindings']
    missing = [
        element[key]
        for element in _widget(plugin_id)['elements']
        for key in _slot_names(element)
        if element[key] not in bindings
    ]
    assert missing == [], (plugin_id, missing)


@pytest.mark.parametrize('plugin_id', FAMILY)
def test_sample_renders_fresh_without_blank_elements(plugin_id: str):
    rendered = render_sample(PLUGINS / plugin_id)
    assert rendered['status'] == 'fresh', (plugin_id, rendered.get('cause'))
    blanks = [
        (element.get('binding'), element.get('reason'))
        for element in rendered['elements']
        if element['state'] != 'ok'
    ]
    assert blanks == [], (plugin_id, blanks)


@pytest.mark.parametrize('plugin_id', FAMILY)
def test_sample_is_an_ok_snapshot(plugin_id: str):
    sample = _sample(plugin_id)
    assert sample['state'] == 'ok'
    assert sample['checkedAt']


@pytest.mark.parametrize('plugin_id', FAMILY)
def test_sample_respects_list_and_sparkline_caps(plugin_id: str):
    elements = _widget(plugin_id)['elements']
    bindings = _sample(plugin_id)['bindings']
    for element in elements:
        if element['type'] == 'list':
            assert len(bindings[element['rowsBinding']]) <= 8, plugin_id
        elif element['type'] == 'sparkline':
            points = bindings[element['pointsBinding']]
            assert 12 <= len(points) <= 30, (plugin_id, len(points))


@pytest.mark.parametrize('plugin_id', FAMILY)
def test_permissions_stay_minimal_and_scoped(plugin_id: str):
    permissions = _manifest(plugin_id)['permissions']
    assert permissions['filesystem']['write'] == []
    assert permissions['network']['allow'] == []
    assert permissions['llm']['allow'] is False
    assert permissions['shell'] == 'none'
    for pattern in permissions['filesystem']['read']:
        assert pattern.startswith('${workspace}/'), (plugin_id, pattern)


@pytest.mark.parametrize('plugin_id', CALENDAR_SOURCES)
def test_calendar_plugins_read_only_the_calendar_bridge(plugin_id: str):
    assert _manifest(plugin_id)['permissions']['filesystem']['read'] == []
    assert _widget_contribution(plugin_id)['dataSource'] == {'type': 'calendar-read'}


@pytest.mark.parametrize(('plugin_id', 'source_type', 'pattern', 'key_column', 'value_column'), WATCH_SOURCES)
def test_watch_plugins_are_scoped_to_their_workspace_glob(
    plugin_id: str, source_type: str, pattern: str, key_column: str, value_column: str
):
    manifest = _manifest(plugin_id)
    source = _widget_contribution(plugin_id)['dataSource']
    assert source['type'] == source_type
    assert source['file'] == pattern
    assert source['keyColumn'] == key_column
    assert source['valueColumn'] == value_column
    assert source['window'] == '30d'
    assert manifest['permissions']['filesystem']['read'] == [pattern]


def test_calendar_today_upgrade_keeps_id_version_and_skill():
    manifest = _manifest('calendar-today')
    assert manifest['id'] == 'calendar-today'
    assert manifest['version'] == '0.2.0'
    assert _widget_contribution('calendar-today')['id'] == 'calendar-today'
    assert 'skills/day-briefing/SKILL.md' in manifest['contributes']['skills']
    skill = PLUGINS / 'calendar-today' / 'skills' / 'day-briefing' / 'SKILL.md'
    assert skill.is_file()
