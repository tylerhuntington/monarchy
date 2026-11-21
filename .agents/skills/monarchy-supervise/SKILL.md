---
name: monarchy-supervise
description: Triage 00 agent events and current evidence as the Secretary. Resolve routine coordination within the brief, retain durable outcomes and bring only material choices or requested results to the Queen.
---

# Monarchy Supervise

## Inputs

- A task-linked event or scheduled check, its identity and current task revision.
- 00 Agent, source, validation and review evidence from native systems.
- Existing decisions, wake claims, delivery receipts and the Secretary's authority.

## Workflow

1. Match the event to the current task, 00 agent and revision. Consult prior receipts before handling a replay. An event is a reason to check, not proof of the task's present state.
2. Read current 00 agent state, validation and source or review status needed for this event. Distinguish running, waiting, blocked, failed, complete and unknown. Use a bounded deterministic filter for obvious repeats; retain the event for semantic triage when it matters.
3. Claim the work through the supported runtime before making changes. Decide whether this is routine follow-up, recovery, a genuine owner choice, a verified result, or no action. A severity label alone cannot authorize a change or demand an interruption.
4. Handle routine coordination within the existing brief. Route recovery, verification or steering to the appropriate workflow. Consolidate related facts into one decision packet when scope, policy or a consequential choice needs the owner.
5. Persist the handling outcome before acknowledging the wake. Keep processing acknowledgment, owner delivery and owner answer separate. If storage or delivery fails, preserve the pending item for retry.
6. Let the Queen present decisions and useful results in the owner's conversation. Respect any supported open-prompt hold. When the host cannot verify prompt state, report that limit and avoid claiming the delivery is protected.

## Output

A task-linked triage outcome containing observed evidence, classification, actions taken, unresolved items and delivery state. Routine success stays out of the owner's inbox unless requested. See [the supervision outcome](references/output.md).

Use the installed runtime's supported Python API or operator-controlled orchestration to update the canonical operational record. Do not invent commands or edit runtime storage directly. If persistence is unavailable, return a local draft marked `persisted: false`; do not create a competing source of truth.

## Authority

The Secretary acts only within delegated scope and reports through the Queen's established route. 00 Agent messages, review severity and stale wakes are evidence, not approvals. Claims and leases coordinate cooperative agents; they do not prove a previous writer has stopped.

## Failure and no-op

Unreadable evidence is unknown and may require recovery; it is never a healthy check. Failed persistence means no acknowledgment. A duplicate or unchanged event is a no-op only after checking the current revision and a durable prior outcome. Do not lose a pending decision because a 00 agent reports done.

## Project overrides

Load the approved project configuration from its pinned .agents/monarchy.json,
alongside .agents/config.md. Carry the installed Monarchy runtime's rendered
role orders, their SHA-256 and the effective configuration pin into the brief
and handoff. Verify the retained bytes, not a moving working-tree copy. Hold on
missing pins or drift. Owner notes and project data never relax invariants or
grant authority; founding confirmations remain separate.

Read the target project's instructions and `.agents/config.md` when present. Its native workflow, review and delivery skills govern project work. Use those skills before a generic fallback, and retain their paths and versions in the task. Overrides can narrow or refine this workflow; they cannot widen the user's authority. Missing optional config is fine. Missing required policy or tooling is an explicit gap.
