# 04: The server-rendered card can be pressed

**What to build:** a card carrying a press draws a real control — a plain form, no script — and posting it answers with a small page showing the explanation or the staged draft.

**Build in:** `src/agentdesk/server/app.py` (`_plugin_element_html`, a new press handler and page), reusing the settings page's form and button classes.

**Blocked by:** 02, 03.

**Status:** ready-for-agent

- [ ] A card whose payload carries `insight.press` renders a `<form method="post" action="/insight/press">` with hidden `kind`, `text`, `subject`, `sender`, `pluginId`, `instanceId` and a submit button labelled with the press's own label; a card without a press renders nothing new.
- [ ] Every hidden value is escaped at the boundary, and the button keeps the existing button markup and accessible name.
- [ ] `POST /insight/press` answers a page that shows: the disclosure lines, then either the explanation or the draft text, with the existing stage form when a thread resolved, and the named refusal sentence when it did not.
- [ ] With the model path off the page says so in the press's own refusal sentence and offers nothing to press again.
- [ ] The page needs no client script and no new inline script; the CSP is unchanged.
- [ ] tests/test_server_insight_press_page.py covers: the form appears with escaped values, absent without a press, an explanation page, a draft page with the stage form, the model-off page, and the refusal page naming the subject.
