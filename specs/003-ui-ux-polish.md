# Spec: Agent Desk SPA UI/UX polish

Seam confirmed by the existing frontend suite: vitest renders the React
shell and cards and asserts on what a person can see and operate. The
stylesheet contract tests in the same suite pin tokens. Playwright
screenshots are evidence of the rendered screens, not a second test
seam. Sources: docs/design-language.md, docs/PRD.md (S1, S2, section 8),
the installed taste, web-interface, and image-to-code skills, and a
read of the current SPA against those rules. VoltAgent/awesome-design-md
has no SKILL.md (verified); the product design language stays the
binding visual system. Linear is the named reference inside that
document, not a second brand to copy.

## Problem Statement

Priya opens Agent Desk on a laptop, and sometimes on a narrow window,
and has to trust what she sees before a meeting. The warm-paper system
is already in the SPA, but several screens still make her work harder
than the design language allows. On a phone-width window the navigation
wraps into three rows and pushes the dashboard down. A file name in the
calendar empty state breaks in the middle of a word, so the path she
must find in OneDrive is hard to read. The marketplace page title is
larger than the one greeting the design language allows, and its focus
ring is suppressed on the main region the skip link targets. Loading,
session-expired, and unreachable states are quiet text with no alert
semantics and no focused recovery. The research bar wears a decorative
sparkle the design language does not allow. Pressing a primary button
does not answer the pointer. Catalog cards put every plugin icon on a
filled chip, which the design language forbids for icons.

## Solution

Polish the existing SPA in place. Keep the warm paper, the one green,
the hairline-and-shadow depth, the type scale, and the sentence-case
voice. Make the narrow window a single scrolling navigation row so the
work starts higher. Keep file names whole. Bring marketplace titles
back to the 28px ceiling, restore a visible focus ring on the skip
target, and speak loading and failure states to assistive tech with the
recovery control next in tab order. Replace the sparkle with the same
search mark the research empty state already uses. Give primary buttons
a pressed state that stays inside color and shadow. Draw catalog icons
as plain strokes, without a filled background.

## User Stories

1. As a manager, I want the dashboard loading state to say it is still reading, so that a slow start does not look frozen.
2. As a manager, I want that loading line announced politely, so that a screen reader does not stay silent.
3. As a manager, I want a failed load to name the problem and the next step, so that I know to try again or restart the app.
4. As a manager, I want the failure announced as an alert, so that I hear it without hunting for it.
5. As a manager, I want focus to land on the failure heading, so that Try again is the next keypress.
6. As a manager, I want an expired session to say to open the shortcut, so that I do not type a token by hand.
7. As a manager, I want the expired-session message announced as an alert, so that the recovery is obvious.
8. As a manager, I want loading copy to use a single ellipsis character, so that the status reads as one word.
9. As a manager, I want the calendar file name to stay on one line, so that I can match it in OneDrive.
10. As a manager, I want a long file name to wrap as a whole token onto the next line, so that a narrow card does not slice the name.
11. As a manager, I want the same treatment for any code token inside an empty state, so that paths and ids stay readable.
12. As a manager on a narrow window, I want navigation in one row, so that the greeting and cards start higher on the screen.
13. As a manager, I want to scroll that row sideways to reach every destination, so that nothing is clipped away.
14. As a manager, I want the brand to stay put while the row scrolls, so that I still know which app I am in.
15. As a manager, I want each navigation item at least 44px tall on that strip, so that a finger can hit it.
16. As a manager using the keyboard, I want the sticky strip not to cover the control I tab to, so that the focus ring stays visible.
17. As a manager, I want the skip link to land on the main region and show a ring, so that I can see where I arrived.
18. As a manager, I want marketplace page titles at the same 28px size as the dashboard greeting, so that the product has one ceiling.
19. As a manager, I want those titles to stay 28px on a narrow window, so that the phone does not invent a second scale.
20. As a manager, I want section labels in sentence case, so that the voice matches the rest of the desk.
21. As a manager, I want marketplace eyebrows in sentence case, so that "Marketplace" is not shouted.
22. As a manager, I want primary buttons to darken slightly while pressed, so that the click answers.
23. As a manager, I want that press to be color only, so that the card does not jump.
24. As a manager, I want the press to disappear instantly when I prefer reduced motion, so that the desk stays still.
25. As a manager, I want the research bar to use the same search mark as the empty research card, so that the two belong together.
26. As a manager, I want that mark hidden from assistive tech, so that the field's name is the only name.
27. As a manager, I want the research field named for autofill tools and set not to offer passwords, so that the bar stays a question box.
28. As a manager, I want the question text at body size, so that it matches every other control.
29. As a manager, I want catalog icons drawn as strokes without a filled tile, so that color stays reserved for status and the one action.
30. As a manager, I want plugin detail and pack icons to follow the same rule, so that a plugin looks the same in the grid and on its page.
31. As a manager, I want marketplace search to keep its visible label and its off autocomplete, so that the polish does not drop a working form.
32. As a manager, I want governance and trust loading lines to end with one ellipsis, so that waiting copy matches the dashboard.
33. As a manager, I want the paper, the green, and the card shadow unchanged, so that the desk still feels like the same ledger.
34. As a manager, I want no new motion on scroll, no photographs, and no second accent, so that the polish does not turn the desk into a marketing page.
35. As a manager, I want sample data to stay labeled sample, so that a prettier screen never invents proof.

## Implementation Decisions

- The visual system in the design language wins wherever a marketing-site skill disagrees. No hero entrance, no scroll scene, no photograph, no gradient, no second accent, no display type above 28px.
- Shell states stay centered cards. Loading is a status region with aria-busy. Failure and expiry are alert regions. Focus moves to the heading, which is taken out of the tab order with a negative tabindex, so Try again is next.
- Loading copy ends with the single character ellipsis. The words "Reading the dashboard" stay, so existing readers of that sentence still recognize it.
- File names inside empty states are a nowrap code token. The row may wrap the token as a unit; the token does not break at a hyphen.
- Below the existing 980px shell breakpoint the rail keeps wrapping and does not scroll sideways: both stylesheets already forbid that, so an entry cannot clip. The words hide (the accessible names stay), targets are 44px, and the document gets scroll padding so a focused control clears the strip. The same rules land in the server sheet so the rails match. The dashboard main is programmatically focusable; the marketplace main already is.
- Marketplace titles use the 28px greeting size at every width. Eyebrows, KPI labels, subheads, and marketplace section headings drop uppercase transformation and use sentence case. The 12px stamp size is the floor for those labels.
- The marketplace main keeps a focus ring for keyboard and skip-link focus. The search field's own outline stays suppressed only because the surrounding field already draws the ring on focus-within.
- Primary buttons and the research send control darken with a brightness filter on press. The checkbox box lists its transition properties instead of transitioning every property. Reduced motion already collapses transitions globally and stays that way.
- The research bar reuses the search mark from the shared empty-state icons. The field keeps its accessible name, gains a name attribute, and sets autocomplete off. Its type size is the 14px body size.
- Catalog, detail, and pack icons lose their filled chip. The stroke SVG remains, in the primary green, with no extra background shape.
- Governance and trust loading strings switch the three-dot sequence for the ellipsis character. No other copy changes.
- The committed SPA bundle is rebuilt after the source changes so the Python server serves the polished screens.

## Testing Decisions

A good test asserts on what the screen exposes: roles, names, text, and attributes. It does not assert on private state. The prior art is the shell suite for centered states, the card suite for the calendar empty state, and the stylesheet contract suite for tokens that must survive.

- Shell tests cover the loading status (busy, polite live region, ellipsis copy), the failure alert, the expiry alert, and that the failure heading can take focus.
- The calendar empty-state test covers the file name as one nowrap token whose text is the path with no surrounding spaces.
- Stylesheet contract tests cover the one-row phone rail, the 28px marketplace title ceiling, the absence of a bare outline suppression on the marketplace main, sentence case (no uppercase transform on the labels this spec names), the search-mark command bar, and catalog icons without a filled background.
- npm run check and the full vitest suite stay green. Playwright screenshots before and after are evidence in the pull request, not a CI seam.

## Out of Scope

- Restyling the desk as a marketing site, including photographs, shader scenes, hero entrances, and staggered motion. The taste skill's landing-page rules conflict with the design language and are not applied.
- Copying Linear, Stripe, or any other DESIGN.md from awesome-design-md. That repository ships no skill, and this product already has a binding design language.
- Server-rendered pages (inbox, assistant, settings, activity, memory, mail, capabilities, peers). They share the idea of the rail but not this SPA's stylesheet.
- A full snap of every 11px, 12.5px, and 13.5px size in the marketplace onto the type scale. The ceiling, the body field, and the stamp floor are in scope; the long tail is deferred so one pass does not redraw every panel.
- Virtualizing the catalog. The bundled catalog is under the threshold where virtualization pays.
- Putting customize mode, filters, or search into the URL.
- New features, new colors, or a dark theme.

## Further Notes

Audit notes that informed the stories, kept short so the tickets can carry the work:

- Web interface guidelines: the marketplace main suppresses outline on focus; loading strings use three dots; the shell states lack alert and status semantics; the research field has no name; checkbox transition uses all; sticky navigation can cover focus on the wrapped phone rail.
- Design language: sentence case everywhere; 28px is the ceiling; no decorative icons; no icon backgrounds; color and shadow only for motion; one accent.
- Taste skill, the parts that do not fight the design language: one system, equal content edges, keyboard focus visible and not under a bar, controls tall enough to hit, no decorative mark that is not the product. The parts that demand a hero, photographs, and scroll scenes are waived because this is an instrument, not a company homepage.
- Image-to-code was read and not used to generate a new visual. The current screens are the reference. Generating a parallel marketing comp would replace the design language instead of polishing it.
- awesome-design-md: `npx skills add VoltAgent/awesome-design-md --list --full-depth` reports no valid skill. Nothing from that repo was invented into a SKILL.md.
