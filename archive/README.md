# Archive: the retired in-box plugin set

The 23 plugin trees in this folder were retired from the product on
2026-11-19 (spec 015, issue #188). They are the AI-built demo set that shipped
with the 2026-11-18 plugin release.

Only two of the 25 in-box plugins were bound to the six desk cards the owner
keeps: the workbook tracker (`excel-report`) and the page watch
(`competitor-watch`). The other 23 were demos that diluted the shipped
catalog, its packs, its docs and its maintenance surface.

Rules for this folder:

- It is outside the marketplace registry, the bundled-catalog build and the
  packaged build. Nothing here is listed, installable, updated or packaged by
  the app.
- It is reference-only, not an import queue. Plugins return only through the
  bar written in spec 015: at least one plugin the owner uses weekly with an
  owner-written spec, the same review and tests as core code, a real registry
  digest, and no more than three to five shipped plugins at once.
- Git history is canonical. This folder exists so the retired set stays
  readable without keeping it in the product.

The two surviving plugins remain in `registry/plugins/`.
