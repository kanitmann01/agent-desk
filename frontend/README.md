# The dashboard SPA source

The Nexuus Bot dashboard is a React single-page app. This folder is its
development source. The production build is emitted into
`../src/agentdesk/server/static/spa/` and committed, so end users never
need node: the Python launcher serves the committed bundle directly.

## Rebuilding

    npm ci
    npm run build

Then commit the new contents of `src/agentdesk/server/static/spa/`.
`npm run check` runs the TypeScript compiler only. `npm test` runs the
unit suite (vitest: the design-contract tests and the component
behavior tests).

## What lives here

- `src/components/`: the shared shells. `WidgetCard` is the bento cell
  (the three-part header contract over the hairline-topped foot);
  `Button` is the plain control (one solid-green primary per surface);
  `Stamp` is the freshness stamp with its status dot; `EmptyState` is
  the composed empty row; `CommandBar` is the research bar.
- Fonts: Plus Jakarta Sans Variable and IBM Plex Mono from the
  `@fontsource` packages (SIL OFL 1.1), imported at the top of
  `index.css`. Vite copies their `.woff2` files into the bundle (and
  never inlines one as a `data:` URL; the CSP allows `self` only); the
  license texts in `public/licenses/` ship beside them.
- `src/dashboard/`: the dashboard cards, one branch per source state,
  mirroring the server renderers in `src/agentdesk/server/sales.py`,
  `commitments.py` and `research.py`.
- `src/test/`: the vitest suite. `tokens.test.ts` pins the design
  contract to the stylesheet, the shell HTML, the package manifest and
  the committed bundle; the component suites render the rail, hero,
  command bar, card chrome, button semantics and the honest card
  states in jsdom (the setup stubs the browser APIs jsdom lacks:
  matchMedia, the observers, CSS.supports).
- The styling is one plain stylesheet: no CSS framework, no utility
  classes, no animation library. Every visual behavior is the
  system's own CSS (150-200ms on color, opacity and shadow).
- The server composes everything the dashboard shows as JSON in
  `GET /api/dashboard`; the SPA renders only from that payload. When the
  built bundle is missing (a source checkout without a build), `/`
  falls back to the server-rendered dashboard.

## Constraints the build must keep

- The strict CSP stays: scripts load only from `/static/spa/` (Vite
  emits external module scripts), no inline script anywhere. Motion
  animates via inline style attributes, which is why style-src allows
  `unsafe-inline` (see SECURITY_HEADERS in `app.py` for the exact
  reasoning).
- Every resource URL is self-hosted, fonts included; the app works
  offline by construction.
- The CSP serves the bundled fonts from `self` (`font-src 'self'` in
  SECURITY_HEADERS): same-origin only, like scripts and styles. No font
  host, no `data:` URLs.
- Motion honors the contract: 150-200ms on color, opacity and shadow
  only; no entrances, no stagger, no parallax; every animated behavior
  degrades to an instant state change under `prefers-reduced-motion`.
