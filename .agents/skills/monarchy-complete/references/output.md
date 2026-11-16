# Output contract

This is a workflow receipt, not an assumed runtime schema. Map these facts to the
installed runtime's supported record interface. Keep evidence references in the
canonical task; a local draft is not a second operational store.

```json
{
  "task_id": "canonical identity",
  "brief_revision": "verified revision",
  "endpoint": "owner-requested result",
  "evidence": [],
  "accepted_limits": [],
  "remaining_requirements": [],
  "completion": "complete | incomplete",
  "readback_verified": false,
  "queen_delivery": "pending | delivered",
  "claim_release": "held | released",
  "persisted": false
}
```

Include the canonical task identity when persisting. Evidence references should
identify the exact native source and observed revision, without credentials or
private transcript dumps. Unknown facts remain unknown; a record cannot grant
new authority. Set `persisted` to true only after a successful write and readback.
