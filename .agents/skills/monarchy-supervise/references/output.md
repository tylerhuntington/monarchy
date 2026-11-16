# Output contract

This is a workflow receipt, not an assumed runtime schema. Map these facts to the
installed runtime's supported record interface. Keep evidence references in the
canonical task; a local draft is not a second operational store.

```json
{
  "event_id": "durable event identity",
  "task_revision": "current observed revision",
  "classification": "routine | decision | recovery | result | no_action | unknown",
  "evidence": [],
  "actions": [],
  "outcome_saved": false,
  "wake_acknowledged": false,
  "owner_delivery": "not_needed | pending | presented",
  "persisted": false
}
```

Include the canonical task identity when persisting. Evidence references should
identify the exact native source and observed revision, without credentials or
private transcript dumps. Unknown facts remain unknown; a record cannot grant
new authority. Set `persisted` to true only after a successful write and readback.
