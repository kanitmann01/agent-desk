# Third-party license manifest

The Agent Desk 0.1.0 **Python runtime has no third-party
dependencies**: the app is pure Python standard library. The
runtime itself is CPython, Python Software Foundation license, a
permissive license reviewed separately from bundled components.

The **dashboard SPA bundle does ship third-party work**: React,
motion and the vendored react-bits components compiled into its
JavaScript, and the Plus Jakarta Sans and IBM Plex Mono font files.
Every item is listed with its license in the Dashboard SPA section
below.

The allowlist for any future Python dependency is MIT, Apache-2.0,
BSD-2-Clause, BSD-3-Clause, and ISC; anything outside it fails
the build.

Upstream LICENSE (and NOTICE, where Apache-2.0) files ship inside the install folder for any listed Python dependency. With zero Python dependencies there is nothing to ship on that side; this file is the record that the check ran and passed.

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
| motion 12.43.0 | animation (the framer-motion package) | MIT | yes, compiled into the JavaScript |
| react-bits (vendored components in `frontend/src/vendor/reactbits/`) | Aurora, TiltedCard, Magnet, GradientText, ShinyText, DecryptedText, AnimatedList, LatticeLoader, StatusMark, GlassSurface, GlareHover, CountUp, ClickSpark, SpotlightCard | MIT + Commons Clause | yes, the ones the app imports, compiled into the JavaScript |
| @fontsource-variable/plus-jakarta-sans | Plus Jakarta Sans Variable, the display and UI typeface | OFL-1.1 | yes, the .woff2 files unchanged |
| @fontsource/ibm-plex-mono | IBM Plex Mono, the numeric typeface | OFL-1.1 | yes, the .woff2 files unchanged |
| tailwindcss 4.3.5, @tailwindcss/vite 4.3.5 | styling | MIT | only the CSS it generates |
| clsx 2.1.1 | class name helper | MIT | no, declared but not imported |
| vite 7.3.8 | build tool | MIT | no, development only |
| @vitejs/plugin-react 5.2.0 | build plugin | MIT | no, development only |
| typescript 5.9.3 | type checking | Apache-2.0 | no, development only |

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
  provenance headers pointing at the upstream repository. The vendored
  set adds no npm dependency beyond motion: AnimatedList is vendored
  without its demo rows and the two icon packages they import, and
  TextType and SplitText are in-repo equivalents because the upstream
  ones animate through GSAP, whose license is not on the allowlist.
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
  as such: the runtime libraries (React, react-dom, motion, clsx) and
  the vendored react-bits components are compiled into the bundle's
  JavaScript, and the two font families above are copied into it
  unchanged.
- Test tooling (vitest, jsdom, @testing-library/*, @types/*) runs
  only in the frontend working tree; none of it enters the bundle.

