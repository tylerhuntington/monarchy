# Output contract

This is a workflow receipt, not an assumed runtime schema. Map these facts to the
installed runtime's supported record interface. Keep evidence references in the
canonical task; a local draft is not a second operational store.

```json
{
  "task_id": "task identity",
  "predecessor": "old writer",
  "successor": "new writer",
  "checkpoint": "verified reference",
  "package_sha256": "full digest",
  "active_operations_settled": false,
  "successor_acknowledged": false,
  "custody": "old_owner | transferred | unresolved",
  "transfer_receipt": null,
  "persisted": false
}
```

Include the canonical task identity when persisting. Evidence references should
identify the exact native source and observed revision, without credentials or
private transcript dumps. Unknown facts remain unknown; a record cannot grant
new authority. Set `persisted` to true only after a successful write and readback.
