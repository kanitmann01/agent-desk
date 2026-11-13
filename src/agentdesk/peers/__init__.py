"""Peer-to-peer plugin sharing between desks (issue #67).

Two desks on the same machine share plugins with nothing centralized:
UDP broadcast discovery, pairing by a short code shown on one desk and
entered on the other, and a token-gated read-only peer endpoint whose
installs go through the same shared validator the registry uses.
"""
