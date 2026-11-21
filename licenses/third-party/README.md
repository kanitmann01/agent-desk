# Upstream LICENSE texts

These are unmodified upstream license texts for components that ship inside
the Agent Desk one-folder bundle. The build copies this directory to
`dist/agent-desk/licenses/`. Font license texts are committed separately at
`frontend/public/licenses/` because they ship beside the font files.

Do not edit a license text. To update one, replace the file from the upstream
URL, update this table, and re-run `python scripts/third_party_notices.py`.

| File | Retrieved from | Bytes | SHA-256 |
|---|---|---|---|
| `apache-2.0.txt` | https://www.apache.org/licenses/LICENSE-2.0.txt | 11358 | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` |
| `cryptography-LICENSE.txt` | `cryptography` 48.0.0 wheel, `dist-info/licenses/` (its LICENSE pointer, LICENSE.APACHE and LICENSE.BSD concatenated verbatim in that order) | 13089 | `794a3f0ab8797e0a56065c9d9c619d6e548493f3eb72b1c976c6f1e759408e6c` |
| `react-19.3.1-LICENSE.txt` | https://unpkg.com/react@19.3.1/LICENSE | 1088 | `da6d3703ed11cbe42bd212c725957c98da23cbff1998c05fa4b3d976d1a58e93` |
| `react-dom-19.3.1-LICENSE.txt` | https://unpkg.com/react-dom@19.3.1/LICENSE | 1088 | `da6d3703ed11cbe42bd212c725957c98da23cbff1998c05fa4b3d976d1a58e93` |
| `scheduler-0.28.0-LICENSE.txt` | https://unpkg.com/scheduler@0.28.0/LICENSE | 1088 | `da6d3703ed11cbe42bd212c725957c98da23cbff1998c05fa4b3d976d1a58e93` |
| `python-LICENSE.txt` | `C:\Python314\LICENSE.txt` (CPython 3.14.5) | 34824 | `939d8e9fa591cbaff0d51e777edb4c1002045d2600ce43a1ae28530cecfc5b88` |
| `hermes-agent-LICENSE.txt` | https://github.com/NousResearch/hermes-agent/blob/f6c3eb1/LICENSE (commit `f6c3eb1`) | 1070 | `821556e6336796450ab852d375117b48a4887e71d255794fd6318d99982a5ab6` |

Retrieved 2026-11-16 (cryptography 2026-11-18; Hermes Agent 2026-11-20). React, React DOM and
Scheduler are MIT; CPython is the Python Software Foundation License
(PSF-2.0); cryptography is dual licensed Apache-2.0 OR BSD-3-Clause and its
file carries both texts behind the package's own pointer note; Apache-2.0
stands alone for the plugin SDK boundary and for Apache-2.0 build-only
components.
