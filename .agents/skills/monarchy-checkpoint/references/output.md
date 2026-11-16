# Output contract

This is a workflow receipt, not an assumed runtime schema. Map these facts to the
installed runtime's supported record interface. Keep evidence references in the
canonical task; a local draft is not a second operational store.

```json
{
  "task_id": "canonical identity",
  "brief_revision": "current revision",
  "writer": "unchanged owner",
  "evidence": [],
  "active_operations": [],
  "unknown_outcomes": [],
  "pending_decisions": [],
  "next_safe_action": "bounded continuation",
  "policy_and_skill_pins": {},
  "readback_verified": false,
  "persisted": false
}
```

Include the canonical task identity when persisting. Evidence references should
identify the exact native source and observed revision, without credentials or
private transcript dumps. Unknown facts remain unknown; a record cannot grant
new authority. Set `persisted` to true only after a successful write and readback.
