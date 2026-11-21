"""The decision vocabulary behind the audit page's activity trail.

The audit store records every inbox decision under a dotted action name;
this module owns the mapping from those names to the plain words the
activity trail renders. The old /activity page that first used it is a
302 into Settings now, so only the vocabulary remains.
"""

# The decision vocabulary and the plain word each renders as.
DECISIONS = {
    "inbox.approved": "approved",
    "inbox.denied": "denied",
    "inbox.edited": "edited",
    "inbox.snoozed": "snoozed",
    "inbox.more-info": "more-info",
    "inbox.pending": "pending",
    "inbox.restored": "restored",
    "demo.seeded": "sample on",
    "demo.cleared": "sample off",
}
