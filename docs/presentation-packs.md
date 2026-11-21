# Installing your own presentation template

The repository ships the pack format and one neutral starter. A pack you
build from your own shells stays on your machine, under
`~/.agent-desk/templates/` (or the directory in `AGENTDESK_TEMPLATES`).
Do not commit that pack, and do not copy it into `registry/plugins/`.

Point the command at the two variant files in your Downloads folder.
They are two variants of one template:

```
python tools/pack_builder.py --id my-template \
    --dark ~/Downloads/dark.pptx \
    --light ~/Downloads/light.pptx
```

The command drops sample slides (and their notes, relationships and
parts), clears author and company metadata, removes SharePoint custom
XML, revision history, thumbnails, comment authors and leftover media,
and replaces a role-labelled typeface or a hard-coded calendar date
when it finds one. The picker on `/agents` then lists
the pack next to the starter. Dark and light are one template. The three
recipes are a generic briefing, a QBR, and a competitor brief.
