# Competitor Watch

## What it answers

Did the competitor pricing page change since the last check, and what changed?

## What it reads

One public page, `https://example.com/pricing`, through the host's http-get
source. The host hashes the response, compares it with the previous read and
returns the changed lines. It reads no local files.

## What it never does

It never follows a redirect, never reads another host, never logs in, never
sends anything to the page, and never reads a workspace file.

## Distribution

This is the only network plugin in the registry. It is excluded from every
pack and is not installed by a pack install. It needs an admin network
approval for `example.com` before it can read the page; without that grant the
card renders blank and says the host has no network permission.
