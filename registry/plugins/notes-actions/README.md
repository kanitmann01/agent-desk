# Notes Actions

## What it answers

Which action items are still open under the Actions heading in my notes, and what is due next?

## What it reads

Checkbox lines under a heading called Actions in ${workspace}/notes/*.md. The host parses the markdown, counts open and done items and finds the earliest due date written in the item text.

## What it never does

It never edits, renames or archives a note, never reads a file outside the notes glob, never calls a model, and never opens a network connection.

Part of the research and knowledge family. Declarative: the manifest names the
data source and the host supplies every value; the plugin ships no code.
