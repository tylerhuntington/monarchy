---
name: monarchy-dispatch
description: Launch or resume a ready task through a verified runtime adapter, with one writer and a complete pinned 00 agent package. Use after dependencies and authority are satisfied, never as a planning shortcut.
---

# Monarchy Dispatch

## Inputs

- A ready task, revision, owner authority, scope and completion contract.
- Verified runtime capabilities, current writer claim and resource budget.
- Selected skill versions, exact project policy files and package hashes.

## Workflow

1. Re-read the task and dependency evidence. Check that no decision, ownership conflict or required capability blocks dispatch. Select only the skills this task needs.
2. Build a complete package through `monarchy.skills.build_package`. Include explicitly selected project instructions and their hashes. Record the archive SHA-256, skill versions and policy revision in the brief. The archive is material to read, not something to execute.
3. Check for an existing task session and reconcile any earlier uncertain launch. Acquire the runtime's supported task ownership claim before a new writer begins. If the runtime lacks that mechanism, keep dispatch held for an operator.
4. Name a new task session with numeric `00-` and a short job description, such as `00-tests` or `00-build-fix`. Use `metadata.agent_name` for a readable descriptor, or let the runtime derive it from the task ID. Keep the native session ID as its identity. Launch or resume through the supported adapter only within the authorized operation. Preserve the selected provider, model and effort. Send the endpoint, scope, authority, report route and pinned package together.
5. Read back the session identity and its binding to the task. Obtain a 00 agent receipt confirming the package pin and scope before treating the 00 agent as ready. A launch response alone is not a receipt.
6. Record the session, claim, package receipt and first checkpoint. If delivery is uncertain, reconcile the same operation instead of creating a second 00 agent.

## Output

A dispatch receipt with task and session identities, package SHA-256, selected versions, policy pins, writer claim and 00 agent acknowledgment. State `ready`, `held` or `launch_uncertain`. See [the dispatch receipt](references/output.md).

Use the installed runtime's supported Python API or operator-controlled orchestration to update the canonical operational record. Do not invent commands or edit runtime storage directly. If persistence is unavailable, return a local draft marked `persisted: false`; do not create a competing source of truth.

## Authority

The Queen or a specifically delegated dispatcher may launch work already authorized in the brief. 00 Agents do not recruit more 00 agents. Installing or reading a skill starts nothing, and a package never grants permissions beyond the owner's words.

## Failure and no-op

Missing resources, hash mismatch, rejected claim or unavailable adapter prevents launch. A launch timeout is unknown, not failure: look for its result before retrying. If the exact task already has a healthy, acknowledged 00 agent, return that binding as a scoped no-op.

## Project overrides

Load the approved project configuration from its pinned .agents/monarchy.json,
alongside .agents/config.md. Carry the installed Monarchy runtime's rendered
role orders, their SHA-256 and the effective configuration pin into the brief
and handoff. Verify the retained bytes, not a moving working-tree copy. Hold on
missing pins or drift. Owner notes and project data never relax invariants or
grant authority; founding confirmations remain separate.

Read the target project's instructions and `.agents/config.md` when present. Its native workflow, review and delivery skills govern project work. Use those skills before a generic fallback, and retain their paths and versions in the task. Overrides can narrow or refine this workflow; they cannot widen the user's authority. Missing optional config is fine. Missing required policy or tooling is an explicit gap.
