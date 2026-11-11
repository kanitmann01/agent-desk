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
  restricted; this is an internal tool, not sold). Only CSS and
  motion-based components: no WebGL, no shaders, no three.js, no ogl.
  SplitText is an in-repo equivalent: the upstream component animates
  through GSAP, which is outside the repo's permissive license
  allowlist, so the same effect is built on motion (MIT).
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
- Every resource URL is self-hosted; the app works offline by
  construction.
