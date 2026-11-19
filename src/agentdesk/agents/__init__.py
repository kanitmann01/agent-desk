"""Agents: the host-side task layer, one runner for every kind.

A registry entry describes a task the desk can run (its id, name,
blurb, artifact kind, model instructions and context need); the runner
owns the parts every agent shares, so a kind never touches memory or
the endpoint itself: the recall, the one prompt, the honest recording.
"""
