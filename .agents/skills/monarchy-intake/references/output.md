# Output contract

This is a workflow receipt, not an assumed runtime schema. Map these facts to the
installed runtime's supported record interface. Keep evidence references in the
canonical task; a local draft is not a second operational store.

```json
{
  "request_source": "conversation reference",
  "project": "repository identity",
  "scope": "requested change",
  "endpoint": "observable owner-requested result",
  "authority_source": "exact request or standing grant",
  "readiness": "ready | decision_needed | attached | no_action",
  "open_questions": [],
  "persisted": false
}
```

Include the canonical task identity when persisting. Evidence references should
identify the exact native source and observed revision, without credentials or
private transcript dumps. Unknown facts remain unknown; a record cannot grant
new authority. Set `persisted` to true only after a successful write and readback.
