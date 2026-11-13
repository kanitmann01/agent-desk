---
name: research-recap
description: Recap the latest stored research answer for the research card. Reads the local research store (summary, source count, answered time; no endpoint call happens) and writes one plain-language recap naming what was answered and how well it was sourced.
---

# Research recap

Reads the latest stored research answer and writes a short recap.

Use it when the user asks what the research desk last found. Restate the
summary in one sentence, then name how many sources back it and when it
was answered. Read the store only: the recap never triggers a new
research call.
