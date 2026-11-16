---
name: monarchy-intake
description: Turn a new owner request into a scoped Monarchy work item, with a clear endpoint and explicit authority. Use before planning or dispatch; use adoption for work already in flight.
---

# Monarchy Intake

## Inputs

- The owner's request and its durable source, including later corrections.
- Target project, current task index, project instructions and existing grants.
- The smallest useful outcome the owner can inspect.

## Workflow

1. Read the request in its conversation. Separate the requested outcome, constraints and open choices. Keep exact authorization evidence; a 00 agent's interpretation is not a new grant.
2. Search the canonical task index for existing ownership. Attach a clarification to its task instead of opening a duplicate. A task already running belongs in adoption or steering.
3. Write a brief with the target, scope, exclusions, observable endpoint, evidence needed, risk limits and permission source. State uncertain facts as uncertain.
4. Resolve ordinary implementation choices from project conventions. Bring a question to the Queen only when its answer changes the outcome, authority or an irreversible step. Independent research may continue while that choice stays open.
5. Record one intake result: ready for composition, needs a specific decision, attached to an existing task, or no actionable work. A ready brief is the gate for composition, not permission to launch.

## Output

A task-linked brief with the request source, scope, endpoint, authority, known dependencies and unresolved questions. Return the task identifier and readiness reason. See [the intake receipt](references/output.md).

Use the installed runtime's supported Python API or operator-controlled orchestration to update the canonical operational record. Do not invent commands or edit runtime storage directly. If persistence is unavailable, return a local draft marked `persisted: false`; do not create a competing source of truth.

## Authority

The Queen owns intake. A Secretary may prepare the brief within a delegated assignment. The user's existing permission persists, but the brief cannot extend it. Intake does not create sessions, change project code or contact people.

## Failure and no-op

An unreadable request, missing target or conflicting owner instructions makes intake incomplete. Ask one focused question through the Queen and preserve useful findings. A duplicate request is a scoped no-op only after linking its existing task; an empty search caused by an error is not proof that no task exists.

## Project overrides

Read the target project's instructions and `.agents/config.md` when present. Its native workflow, review and delivery skills govern project work. Use those skills before a generic fallback, and retain their paths and versions in the task. Overrides can narrow or refine this workflow; they cannot widen the user's authority. Missing optional config is fine. Missing required policy or tooling is an explicit gap.
