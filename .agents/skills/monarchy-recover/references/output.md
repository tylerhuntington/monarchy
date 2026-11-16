# Output contract

This is a workflow receipt, not an assumed runtime schema. Map these facts to the
installed runtime's supported record interface. Keep evidence references in the
canonical task; a local draft is not a second operational store.

```json
{
  "failure_class": "quiet | waiting | dead | unreachable | stale_claim | uncertain_write",
  "operation_ids": [],
  "reconciled_evidence": [],
  "custody": "known | unresolved",
  "action": "one bounded repair or hold",
  "attempts_used": 0,
  "postcondition": "verified | unknown | failed",
  "next_check": "specific evidence needed",
  "persisted": false
}
```

Include the canonical task identity when persisting. Evidence references should
identify the exact native source and observed revision, without credentials or
private transcript dumps. Unknown facts remain unknown; a record cannot grant
new authority. Set `persisted` to true only after a successful write and readback.
