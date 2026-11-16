# Output contract

This is a workflow receipt, not an assumed runtime schema. Map these facts to the
installed runtime's supported record interface. Keep evidence references in the
canonical task; a local draft is not a second operational store.

```json
{
  "brief_revision": "pinned brief revision",
  "tasks": [
    {
      "task_id": "task identifier",
      "writer_scope": [
        "explicit paths or resources"
      ],
      "depends_on": [],
      "entry_conditions": [],
      "endpoint": "one inspectable result",
      "verification": "native workflow and evidence",
      "state": "ready | held"
    }
  ],
  "integration_owner": "one designated role",
  "persisted": false
}
```

Include the canonical task identity when persisting. Evidence references should
identify the exact native source and observed revision, without credentials or
private transcript dumps. Unknown facts remain unknown; a record cannot grant
new authority. Set `persisted` to true only after a successful write and readback.
