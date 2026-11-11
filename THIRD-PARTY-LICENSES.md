# Third-party license manifest

Agent Desk 0.1.0 ships **no third-party components**: the app is
pure Python standard library. The runtime itself is CPython,
Python Software Foundation license, a permissive license reviewed
separately from bundled components.

The allowlist for any future component is MIT, Apache-2.0,
BSD-2-Clause, BSD-3-Clause, and ISC; anything outside it fails
the build.

Upstream LICENSE (and NOTICE, where Apache-2.0) files ship inside the install folder for any listed component. With zero components there is nothing to ship; this file is the record that the check ran and passed.
