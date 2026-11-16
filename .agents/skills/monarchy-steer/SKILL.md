---
name: monarchy-steer
description: Apply a new owner instruction to work already in flight, preserving one writer and valid evidence. Use for scope or priority changes, not for routine status checks or a new unrelated request.
---

# Monarchy Steer

## Inputs

- The new instruction and its source, current brief and task revision.
- Active 00 agent, tools, validation runs and ownership claims.
- Dependencies, open decisions and evidence potentially invalidated by the change.

## Workflow

1. Read the new message against the original objective. Classify it as clarification, priority, scope, cancellation or a separate task. A question about status does not cancel ongoing work.
2. Determine what the instruction actually authorizes. Update only affected scope and mark any new permission gap for the Queen.
3. Observe active writes and validation before changing direction. Send steering through the supported runtime route. For a cancellation or conflicting change, obtain evidence that the old action stopped or settled before a replacement writer begins.
4. Revise the canonical brief and dependency graph with the instruction source. Preserve completed work still valid for the new scope, and invalidate evidence whose inputs or endpoint changed.
5. Require the 00 agent to acknowledge the new revision. Reconcile outstanding decisions and reports against it; supersede stale choices explicitly rather than dropping them.
6. Record the steering receipt and the next expected evidence. If delivery is uncertain, keep the old 00 agent state visible and reconcile instead of resending blindly.

## Output

A steering receipt with old and new brief revisions, affected work, retained and invalidated evidence, active-write status and the 00 agent's acknowledgment. See [the steering receipt](references/output.md).

Use the installed runtime's supported Python API or operator-controlled orchestration to update the canonical operational record. Do not invent commands or edit runtime storage directly. If persistence is unavailable, return a local draft marked `persisted: false`; do not create a competing source of truth.

## Authority

The owner's instruction defines the change. The Queen or delegated Secretary may relay it within existing authority. A steer is not approval of unrelated actions, and an interrupted conversation is not proof an external command stopped.

## Failure and no-op

Uncertain cancellation, lost delivery or an unacknowledged revision blocks conflicting replacement work. Continue independent work only when its scope is still valid. A repeated steer already acknowledged for the same revision is a no-op after checking the 00 agent binding.

## Project overrides

Read the target project's instructions and `.agents/config.md` when present. Its native workflow, review and delivery skills govern project work. Use those skills before a generic fallback, and retain their paths and versions in the task. Overrides can narrow or refine this workflow; they cannot widen the user's authority. Missing optional config is fine. Missing required policy or tooling is an explicit gap.
