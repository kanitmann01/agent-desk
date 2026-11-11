# The dashboard SPA source

The Agent Desk dashboard is a React single-page app. This folder is its
development source. The production build is emitted into
`../src/agentdesk/server/static/spa/` and committed, so end users never
need node: the Python launcher serves the committed bundle directly.

## Rebuilding

    npm ci
    npm run build

Then commit the new contents of `src/agentdesk/server/static/spa/`.
`npm run check` runs the TypeScript compiler only.

## What lives here

- `src/vendor/reactbits/`: components vendored from react-bits
  (github.com/DavidHDev/react-bits, MIT plus Commons Clause: free for
  personal and commercial use, selling the library itself is
  restricted; this is an internal tool, not sold). Each file carries a
  provenance header naming its upstream path and the commit it was
  fetched from. The shadcn CLI route (`npx shadcn@latest add
  @react-bits/<Name>-TS-TW`) wants to scaffold a shadcn project first,
  so files are fetched from upstream `src/ts-tailwind/` by hand.
  No component brings an npm dependency beyond motion (MIT):
  - Aurora (the page backdrop) is the one WebGL component: raw WebGL2
    with its own shaders, no ogl, no three.js. Without WebGL2 its canvas
    stays empty and the static wash in `index.css` shows instead.
    GlassSurface is mounted with `renderer="svg"`, so its optional
    WebGL path never activates. Everything else is CSS, 2D canvas or
    motion.
  - AnimatedList is vendored without its demo rows and the two icon
    packages they import (the one local change, stated in its header).
  - TextType and SplitText are in-repo equivalents: the upstream
    components animate through GSAP, which is outside the repo's
    permissive license allowlist, so the same effects are built on
    plain timers and on motion.
- `src/components/`: the shells built on those parts. `Backdrop` is
  mounted outside `React.StrictMode` on purpose (the reason is in the
  file); `WidgetCard` is the bento cell with its plain, star and tilt
  shells; `CommandBar` is the research bar.
- Fonts: Inter Variable and Space Grotesk Variable from
  `@fontsource-variable` (SIL OFL 1.1), imported at the top of
  `index.css`. Vite copies their `.woff2` files into the bundle; the
  license texts in `public/licenses/` ship beside them.
- `src/dashboard/`: the dashboard cards, one branch per source state,
  mirroring the server renderers in `src/agentdesk/server/sales.py`,
  `commitments.py` and `research.py`.
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
- The CSP has no `font-src` directive today, so in production the
  bundled fonts are blocked (font loads fall back to `default-src
  'none'`) and the system stacks in `index.css` render instead. The dev
  server sends no CSP, so the fonts do show there. Adding
  `font-src 'self'` to SECURITY_HEADERS is the one-line change that
  lets them load; that is the owner's decision, not the build's.
- Motion is honest: every animated component honors
  `prefers-reduced-motion`, and the card entrances, the tilt, the typing
  answer and the command bar sweep all render their final state at once
  when it is set.
