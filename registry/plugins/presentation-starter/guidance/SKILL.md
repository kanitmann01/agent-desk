# Filling a presentation template

Adapted from the Anthropic pptx skill (Apache-2.0). Changed: the rules
are prompt text for this desk, not a shell skill, and the scripts are
not included. House rules for sources are marked "House".

## Use the deck tools

The pack declares four host tools. They need no model endpoint, and the
host runs them: no code from this plugin executes.

| Tool | Input | What it returns |
| --- | --- | --- |
| `presentation_outline` | `brief`, optional `template`, `recipe` | Slide text as JSON |
| `presentation_create` | `brief` or `outline`, optional `variant`, `render` | A `.pptx` and its download address |
| `presentation_inspect` | `file` | Slide text, notes, package problems |
| `presentation_render` | `file` | A PDF and slide images, when a renderer exists |

HTTP: `POST /api/presentation/tools` with
`{"tool": "presentation_create", "brief": "the Q3 review"}`. List the
live schemas at `GET /api/presentation/tools`. The CLI is the same
surface:

```
python -m agentdesk.presentations.cli create --brief "the Q3 review" --out q3.pptx
python -m agentdesk.presentations.cli inspect q3.pptx
```

Use `outline` first when you want to review the story, then `create`
with that outline. Always `inspect` a deck before you hand it over.
Paths stay inside the presentation folder.

## Fill the shell

- Use the layout the recipe names. Do not restyle the master, the logo,
  the footer, or the artwork.
- Replace placeholder text. Leave no "Title goes here" and no
  "Divider Slide Option" in the file you hand over.
- One idea on a content slide. A title, then two to five bullets.
- Body text stays at 14 pt or larger. If the words do not fit, shorten
  them or continue on the next slide. Do not shrink the type.
- A shell with no body placeholder gets a text box in the recipe's
  region, in the recipe's font and colour.

## Sources

House: every content slide lists its sources in the speaker notes.
House: a number appears only when a source supplied it. Where a number
is missing, write a visible "data needed" marker. Never invent a figure.

## Check before you finish

- The package opens. Every relationship points at a part that exists.
- No empty title.
- No leftover placeholder text.
- A renderer may substitute fonts. A fit that looks right in a
  substitute face can still be tight in the face the shell names.
