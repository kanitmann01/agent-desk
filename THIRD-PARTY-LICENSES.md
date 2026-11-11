# Third-party license manifest

Agent Desk 0.1.0 ships **no third-party components**: the app is
pure Python standard library. The runtime itself is CPython,
Python Software Foundation license, a permissive license reviewed
separately from bundled components.

The allowlist for any future component is MIT, Apache-2.0,
BSD-2-Clause, BSD-3-Clause, and ISC; anything outside it fails
the build.

Upstream LICENSE (and NOTICE, where Apache-2.0) files ship inside the install folder for any listed component. With zero components there is nothing to ship; this file is the record that the check ran and passed.

## Dashboard SPA (development-time toolchain only)

The dashboard UI is a React single-page app built in `frontend/`. The
toolchain below runs only at development time: end users receive the
committed build output (`src/agentdesk/server/static/spa/`) and never
need node, npm, or any of these packages at runtime.

| Component | Used for | License |
|---|---|---|
| react 19.3.1 | UI library | MIT |
| react-dom 19.3.1 | DOM renderer | MIT |
| vite 7.3.8 | build tool (dev) | MIT |
| @vitejs/plugin-react 5.2.0 | build plugin (dev) | MIT |
| typescript 5.9.3 | type checking (dev) | Apache-2.0 |
| tailwindcss 4.3.5, @tailwindcss/vite 4.3.5 | styling (dev build) | MIT |
| motion 12.43.0 | animation (the framer-motion package) | MIT |
| clsx 2.1.1 | class name helper | MIT |
| react-bits (vendored components in `frontend/src/vendor/reactbits/`) | SpotlightCard, GlassSurface, GlareHover, CountUp, ClickSpark | MIT + Commons Clause |

License notes:

- React, react-dom, Vite, @vitejs/plugin-react, Tailwind CSS, motion
  and clsx are MIT; typescript is Apache-2.0 (with its NOTICE in the
  upstream package). Upstream license texts live in each package under
  `frontend/node_modules/<package>/LICENSE*` after `npm install`, and
  in the npm registry metadata for each version pinned in
  `frontend/package.json`.
- react-bits (github.com/DavidHDev/react-bits) is MIT plus Commons
  Clause: free for personal and commercial use; the restriction is on
  selling the library itself. Agent Desk is an internal tool, not sold,
  so the restriction does not apply. The vendored component files carry
  provenance headers pointing at the upstream repository.
- Only the built bundle ships to users. No package is distributed: the
  built JavaScript is Agent Desk's own artifact.

