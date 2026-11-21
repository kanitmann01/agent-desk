# Third-party license manifest

The Agent Desk 0.1.0 **Python runtime ships 2 third-party dependencies**:

| Component | Version scoped in pyproject | Used for | License |
|---|---|---|---|
| cryptography | pinned in pyproject | memory encryption at rest (AES-256-GCM field encryption, HKDF key derivation and HMAC blind indexes) | Apache-2.0 OR BSD-3-Clause |
| keyring | pinned in pyproject | API keys in the OS keychain (model-connection secrets; the second runtime dependency, spec 018) | MIT |

The runtime itself is CPython, Python Software Foundation
license, a permissive license reviewed separately from bundled
components.

The **dashboard SPA bundle does ship third-party work**: React
compiled into its JavaScript, and the Geist, Geist Mono, and
Montserrat font files. Every item is listed with its license in the
Dashboard SPA section below.

The allowlist for any Python dependency is MIT, Apache-2.0,
BSD-2-Clause, BSD-3-Clause, and ISC; anything outside it fails
the build.

Upstream LICENSE (and NOTICE, where Apache-2.0) files ship inside the install folder for any listed Python dependency.

## Dashboard SPA (what the bundle ships, and the toolchain that builds it)

The dashboard UI is a React single-page app built in `frontend/`. End
users receive the committed build output
(`src/agentdesk/server/static/spa/`) and never need node, npm, or the
build tools. The last column says which items are inside that output
and which only run at development time.

| Component | Used for | License | In the shipped bundle |
|---|---|---|---|
| react 19.3.1 | UI library | MIT | yes, compiled into the JavaScript |
| react-dom 19.3.1 | DOM renderer | MIT | yes, compiled into the JavaScript |
| @fontsource/geist | Geist, the UI face | OFL-1.1 | yes, the .woff2 files unchanged |
| @fontsource/geist-mono | Geist Mono, the numeric typeface | OFL-1.1 | yes, the .woff2 files unchanged |
| @fontsource/montserrat | Montserrat, the display face | OFL-1.1 | yes, the .woff2 files unchanged |
| vite | build tool | MIT | no, development only |
| @vitejs/plugin-react | build plugin | MIT | no, development only |
| typescript 5.9.3 | type checking | Apache-2.0 | no, development only |

License notes:

- React, react-dom, Vite and @vitejs/plugin-react are MIT; typescript
  is Apache-2.0 (with its NOTICE in the upstream package). Upstream
  license texts live in each package under
  `frontend/node_modules/<package>/LICENSE*` after `npm install`, and
  in the npm registry metadata for each version pinned in
  `frontend/package.json`.
- The dark-glass theme's vendored react-bits components (MIT plus
  Commons Clause) and its animation, styling and class-helper packages
  left with that theme: the warm-paper system
  (docs/design-language.md) is drawn entirely in the repo's own
  stylesheet and components. Nothing in the bundle carries a Commons
  Clause obligation anymore.
- The two font families come from their @fontsource packages under
  the SIL Open Font License 1.1 (OFL-1.1). Unlike the rest of this
  table, the fonts themselves ship: the build copies their .woff2 files
  into the bundle, so the app never fetches a font from another origin.
  The OFL allows bundling and redistribution with software and asks
  that the copyright notice and license travel with the fonts: both
  license texts are committed in `frontend/public/licenses/` and the
  build emits them next to the fonts, in
  `src/agentdesk/server/static/spa/licenses/`. OFL-1.1 is a font
  license and is not on the allowlist above, which gates the Python
  dependencies declared in pyproject; the fonts are listed here so the
  record is complete.
- Only the built bundle ships to users. No npm package is distributed
  as such: the runtime libraries (React, react-dom) are compiled into
  the bundle's JavaScript, and the two font families above are copied
  into it unchanged.
- Test tooling (vitest, jsdom, @testing-library/*, @types/*) runs
  only in the frontend working tree; none of it enters the bundle.
