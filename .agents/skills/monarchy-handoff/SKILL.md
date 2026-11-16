---
name: monarchy-handoff
description: Transfer an owned task or Queen conversation to a named successor with verified custody. Use at a deliberate session transition; a copied checkpoint alone is not a handoff.
---

# Monarchy Handoff

## Inputs

- An authorized transfer, predecessor, successor and exact task scope.
- Verified checkpoint, current record revision, writer claim and active operations.
- Outstanding decisions, authority sources and successor package receipt.

## Workflow

1. Confirm the successor and transfer scope are authorized. Refresh the checkpoint, pending decisions and uncertain operations from current evidence.
2. Settle or explicitly retain custody of active writes. Check the actual operation or runtime state; quiet chat, an expired lease and an interrupted agent are not stop receipts.
3. Give the successor the pinned package and checkpoint. Require acknowledgment of objective, authority, pending choices, unknown outcomes and next safe action while the predecessor remains responsible.
4. Use the runtime's supported ownership transfer to bind the current revision and both identities. Do not improvise a transfer with direct database edits or simultaneous claims. If no supported transfer exists, hold conflicting work for operator orchestration.
5. Verify the new owner in the canonical record and runtime. Only then release the predecessor's responsibility and resume writes under the successor.
6. Retain a transfer receipt. For a Queen succession, keep the owner's single conversation and unanswered questions coherent through the established host route; do not promise a host can move conversations when it cannot.

## Output

A handoff receipt that identifies the previous and new owner, checkpoint and package pins, settled operations, successor acknowledgment and verified custody state. See [the handoff receipt](references/output.md).

Use the installed runtime's supported Python API or operator-controlled orchestration to update the canonical operational record. Do not invent commands or edit runtime storage directly. If persistence is unavailable, return a local draft marked `persisted: false`; do not create a competing source of truth.

## Authority

The authorized coordinator manages transfer; neither worker can expand the task. There is one writer before and after the transition. During uncertainty the predecessor's claim remains unresolved, and the successor may read or prepare without conflicting writes.

## Failure and no-op

If the predecessor cannot be accounted for, the successor cannot acknowledge, or the transfer result is uncertain, keep custody unresolved and enter recovery. Never fill the gap by guessing. A replay of a verified transfer is a no-op after checking the current owner and revision.

## Project overrides

Read the target project's instructions and `.agents/config.md` when present. Its native workflow, review and delivery skills govern project work. Use those skills before a generic fallback, and retain their paths and versions in the task. Overrides can narrow or refine this workflow; they cannot widen the user's authority. Missing optional config is fine. Missing required policy or tooling is an explicit gap.
