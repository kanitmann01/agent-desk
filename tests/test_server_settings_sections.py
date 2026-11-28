"""Settings has six sections and opens on Your AI (spec 022, ticket 022-3).

The person's complaint was that adding a model's key sat at the bottom of a
ten-thousand-pixel page among thirty-two on/off switches. Pinned here from
the outside, on the page a person reads: the section bar, the order, what
each section holds, and that every address that worked before still names
something. Nothing here reads a helper or a stylesheet.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from nexuusbot.keys import health
from nexuusbot.keys.secrets import KeychainSecrets, MemoryKeychain
from nexuusbot.server import pages

SECTIONS = ["ai", "tools", "memory", "preferences", "advanced"]
BAR = ["Your AI", "Your tools", "Memory", "Preferences", "Activity", "Advanced"]
BAR_HREFS = ["#ai", "#tools", "#memory", "#preferences", "/settings/activity", "#advanced"]
# Every anchor the page had before the sections (spec 022's anchor map).
OLD_ADDRESSES = ["connections", "jobs", "sources", "learned", "preferences", "appearance",
                 "desk", "agent", "desk-check", "registry", "machine", "record",
                 "skills", "questions", "endpoint"]


def _instant_check(base_url, api_key, extra_headers=None, timeout=None):
    """A save-time prober that answers instantly and hermetically."""
    return health.ProbeResult(health.OUTCOME_OK, "", ["mock-chat"])


@pytest.fixture()
def env():
    """A booted desk with an in-memory keychain and nothing else saved."""
    booted = server_harness.Booted(keychain=KeychainSecrets(MemoryKeychain()),
                                   connection_check=_instant_check)
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def _page(env, auth) -> str:
    return env.request("GET", "/settings", auth)[2].decode("utf-8")


def _sections(page: str) -> dict:
    """Each section's markup, from its wrapper to the next one (the last
    one runs to the end of the page)."""
    starts = [match.start() for match in re.finditer(r"<div class='settings-section'", page)]
    keys = re.findall(r"data-settings-section='([a-z]+)'", page)
    bounds = starts[1:] + [len(page)]
    return {key: page[start:end] for key, start, end in zip(keys, starts, bounds)}


def _visible(markup: str) -> str:
    """The words a reader sees in a fragment: tags dropped, text unescaped."""
    import html

    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split()).lower()


def _switches(markup: str) -> list:
    """The setting keys of every on/off button in a fragment, in order."""
    return re.findall(r"data-setting='([^']+)'", markup)


def test_the_bar_offers_six_sections_in_order(env, auth):
    page = _page(env, auth)
    bar = page[page.index("data-settings-bar"):]
    bar = bar[:bar.index("</nav>")]
    assert re.findall(r"<a href='([^']+)'>([^<]+)</a>", bar) == list(zip(BAR_HREFS, BAR))


def test_your_ai_comes_first_and_the_key_form_precedes_every_switch(env, auth):
    page = _page(env, auth)
    assert list(_sections(page)) == SECTIONS
    # The key form is on the first screen of the first section, and no
    # on/off switch sits above it anywhere on the page.
    assert page.index("data-settings-section='ai'") < page.index("id='connection-form'")
    assert page.index("id='connection-form'") < page.index("data-setting=")
    # The page is rendered whole and the script shows one section at a time.
    assert "[data-settings-bar]" in pages.APP_JS


def test_the_add_form_asks_for_three_things_and_hides_the_rest(env, auth):
    form = _sections(_page(env, auth))["ai"]
    form = form[form.index("id='connection-form'"):form.index("</form>")]
    before, rest = form.split("<details", 1)
    inside, after = rest.split("</details>", 1)
    outer = before + after
    for shown in ("id='conn-provider'", "id='conn-key'", "id='conn-model'", "Save"):
        assert shown in outer
    for hidden in ("id='conn-base'", "id='conn-label'", "name='isDefault'", "More options"):
        assert hidden in inside and hidden not in outer


def test_four_switches_come_before_advanced_and_the_computer_check_after_it(env, auth):
    page = _page(env, auth)
    marker = page.index("id='settings-advanced'")
    before = _switches(page[:marker])
    # Five: the mail digest's switch, the Outlook alerts switch under it
    # in the sources card (spec 028), and the memory card's three.
    assert len(before) <= 5
    assert sorted(before) == ["mail_enabled", "mail_feeder", "memory_auto_approve",
                              "memory_capture_assistant", "memory_capture_research"]
    # The computer check is for IT and is offered from Advanced only.
    check = page.index('href="/capabilities"')
    assert marker < check
    assert "Computer check (for IT)" in page[check:check + 200]
    assert page.count('href="/capabilities"') == 1


def test_your_ai_says_what_answers_and_shows_the_model(env, auth):
    your_ai = _sections(_page(env, auth))["ai"]
    assert "No AI key is saved yet. Add one below; it takes a minute." in your_ai
    status, _h, _body = env.post_json("/api/connections", {
        "label": "OpenAI personal", "provider": "openai",
        "baseUrl": "http://127.0.0.1:9/v1", "apiKey": "sk-test-0001",
        "model": "mock-chat"}, auth)
    assert status == 201
    your_ai = _sections(_page(env, auth))["ai"]
    assert "<b>OpenAI personal</b> answers everything" in your_ai
    assert "<span class='mono'>mock-chat</span>" in your_ai
    assert "Model: mock-chat" in your_ai  # the saved row names it too
    said = _visible(your_ai)
    for absent in ("not configured", "not set", "none bound", "unbound", "not bound"):
        assert absent not in said, absent
    assert "what uses your ai" in said
    assert "use a different model for one of these" in said


def test_your_tools_shows_each_tools_live_state_and_one_action(env, auth):
    tools = _sections(_page(env, auth))["tools"]
    assert "No sales workbook is connected." in tools
    assert "data-pick" in tools and "Open a workbook" in tools
    assert "No calendar is connected." in tools
    assert "<a class='btn btn-secondary' href='/walkthrough/calendar'>Set up</a>" in tools
    assert "Off. Nothing is read." in tools
    # The mail digest's switch, then the Outlook alerts switch under it
    # in the same card (spec 028 re-homed).
    assert _switches(tools) == ["mail_enabled", "mail_feeder"]
    assert 'action="/settings/mail/folder"' in tools


def test_the_memory_card_explains_how_memory_works_and_how_to_empty_it(env, auth):
    memory = _sections(_page(env, auth))["memory"]
    assert "remembers facts about you and your work" in memory
    assert _switches(memory) == ["memory_auto_approve", "memory_capture_assistant",
                                 "memory_capture_research"]
    assert "data-setting='memory_auto_approve'>On</button>" in memory
    assert "action='/memory/forget-all'" in memory and "Forget everything" in memory
    assert "href='/memory'" in memory
    # What the desk learned about you is its own card and carries no switch.
    learned = memory[memory.index("id='learned'"):]
    assert "data-setting=" not in learned


def test_preferences_holds_the_six_and_the_themes(env, auth):
    preferences = _sections(_page(env, auth))["preferences"]
    assert "id='preferences'" in preferences and "id='appearance'" in preferences
    # Four are choices and two are typed (topics, minutes): six in all.
    assert preferences.count("<select id='pref-") == 4
    assert "id='pref-focusTopics'" in preferences and "id='pref-prepMinutes'" in preferences
    assert "data-setting=" not in preferences


def test_advanced_opens_with_its_one_line_and_holds_the_rest(env, auth):
    page = _page(env, auth)
    advanced = _sections(page)["advanced"]
    assert _visible(advanced).startswith(
        "advanced the defaults are right for most people. change these only if you know why.")
    for anchor in OLD_ADDRESSES:
        assert f"id='{anchor}'" in page, anchor
    for anchor in ("desk", "agent", "desk-check", "endpoint", "registry", "machine",
                   "record", "skills", "questions"):
        assert f"id='{anchor}'" in advanced, anchor
    # The six recommendation switches are rendered once, and only here.
    for key in ("recommendations", "recommend_deadlines", "recommend_meetings",
                "recommend_horizon_days", "recommend_model_rank", "recommend_threshold"):
        assert page.count(f"data-setting='{key}'") == 1, key
        assert f"data-setting='{key}'" in advanced, key
    # The old endpoint card is down to its one remaining field.
    endpoint = advanced[advanced.index("id='endpoint'"):]
    endpoint = endpoint[:endpoint.index("</section>")]
    assert "name='presentationTimeout'" in endpoint
    assert "id='llm-base'" not in endpoint and "id='llm-key'" not in endpoint


def test_what_a_person_reads_never_says_job_binding_or_bound(env, auth):
    said = _visible(_page(env, auth))
    for banned in ("none bound", "unbound", "not bound", " job ", "binding"):
        assert banned not in said, banned


def test_an_address_that_names_a_card_opens_the_section_that_holds_it(env, auth):
    """The script maps every id inside a section to that section, so a
    form's return_to or a saved link lands on the section, then the card."""
    page = _page(env, auth)
    sections = _sections(page)
    holders = {}
    for key, markup in sections.items():
        for element_id in re.findall(r"id='([^']+)'", markup):
            holders.setdefault(element_id, key)
    for card, section in (("connections", "ai"), ("sources", "tools"), ("learned", "memory"),
                          ("appearance", "preferences"), ("skills", "advanced")):
        assert holders[card] == section, card
    # Preferences keeps its card's id as the section's own address.
    assert "data-settings-section='preferences'>" in page
    assert "data-settings-section='ai' id='ai'>" in page
