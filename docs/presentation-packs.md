# Installing your own presentation template

The repository ships the pack format and one neutral starter. A pack you
build from your own shells stays on your machine, under
`~/.agent-desk/templates/` (or the directory in `AGENTDESK_TEMPLATES`).
Do not commit that pack, and do not copy it into `registry/plugins/`.

The confirmed local shells, if you have them, are `brand-Dark.pptx` and
`brand-Light.pptx` in your Downloads folder. They are two variants of one
template:

```
python tools/pack_builder.py --id my-template \
    --dark ~/Downloads/brand-Dark.pptx \
    --light ~/Downloads/brand-Light.pptx
```

The command drops sample slides (and their relationships and parts),
clears author metadata, removes SharePoint custom XML, revision history
and leftover package parts, and fixes a mistyped face name and a
hard-coded date when it finds them. The picker on `/agents` then lists
the pack next to the starter. Dark and light are one template. The three
recipes are a generic briefing, a QBR, and a competitor brief.
