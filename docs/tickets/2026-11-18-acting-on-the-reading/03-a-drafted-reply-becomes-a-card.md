# 03: A drafted reply is staged as a card, never sent

**What to build:** a resolved draft is staged as an inbox suggestion card through the same path a hand-typed reply uses, labelled with its source; accepting it writes the outbox file and nothing else does.

**Build in:** `src/agentdesk/server/app.py` (beside `_mail_draft`), `src/agentdesk/insight/press.py`.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] `POST /api/insight/draft` with `"stage": true` on a resolved reply-draft adds exactly one suggestion card whose `draft` is the composed text, whose origin and title name it as a drafted reply, and whose meta records the resolved thread (message id, recipients, subject) in the shape the existing acceptance path reads.
- [ ] The card's copy names the source: "Drafted by the model" or "Skeleton, not a model draft", so the user knows what they are editing.
- [ ] Accepting that card writes the `.eml` through the single existing outbox writer; no new writer is introduced.
- [ ] A second press with the same thread and the same text stages nothing and answers 200 with `"staged": false` and the existing card's id; an edited text stages a new card.
- [ ] The audit log records the press and the staging with the thread id, and records no message content.
- [ ] tests/test_insight_press.py or a new tests/test_insight_staging.py covers: one card staged with the model text and label, acceptance writes one outbox file, repeat press stages nothing, refusal when unresolved, and the audit entry shape.
