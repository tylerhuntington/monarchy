---
name: monarchy-checkpoint
description: Capture a durable, evidence-linked continuation record before context loss or at a meaningful task boundary. Use to preserve work and open questions; checkpointing does not transfer ownership.
---

# Monarchy Checkpoint

## Inputs

- Current task and brief revision, authoritative record and writer identity.
- Latest source, validation, review and session evidence.
- Pending decisions, unfinished actions, dependencies and the next safe step.

## Workflow

1. Read current native state rather than relying only on conversation memory. Record source revision and external operation identifiers where they determine what can resume safely.
2. Separate completed evidence, work in progress, attempted writes with unknown outcomes, blocked choices and unverified claims. Keep exact links or receipts for important assertions.
3. Write the minimum useful continuation: objective, authority, scope, current owner, files or resources touched, active tools, pending decisions and next safe action. Preserve selected model and skill or policy pins.
4. Remove credentials and unnecessary private transcript content. Keep records in the authorized task store or explicit private handoff location, not a public repository by default.
5. Persist and read back the checkpoint through the supported record interface. Link it to the task and revision; keep it distinct from a transfer or completion receipt.

## Output

A verified checkpoint reference with enough evidence for a successor to reorient, including unknown outcomes and open choices. Report whether persistence and readback succeeded. See [the checkpoint contract](references/output.md).

Use the installed runtime's supported Python API or operator-controlled orchestration to update the canonical operational record. Do not invent commands or edit runtime storage directly. If persistence is unavailable, return a local draft marked `persisted: false`; do not create a competing source of truth.

## Authority

The current task owner may checkpoint its own work. The snapshot copies context; it grants no new permission and releases no writer claim. Preserve the user's original authorization references rather than summarizing them into broader grants.

## Failure and no-op

If the task store cannot be written or read back, return a clearly unpersisted draft and keep ownership. Missing evidence remains a gap in the snapshot. An unchanged checkpoint is a no-op only when the current task revision and external operation state were checked.

## Project overrides

Load the approved project configuration from its pinned .agents/monarchy.json,
alongside .agents/config.md. Carry the installed Monarchy runtime's rendered
role orders, their SHA-256 and the effective configuration pin into the brief
and handoff. Verify the retained bytes, not a moving working-tree copy. Hold on
missing pins or drift. Owner notes and project data never relax invariants or
grant authority; founding confirmations remain separate.

Read the target project's instructions and `.agents/config.md` when present. Its native workflow, review and delivery skills govern project work. Use those skills before a generic fallback, and retain their paths and versions in the task. Overrides can narrow or refine this workflow; they cannot widen the user's authority. Missing optional config is fine. Missing required policy or tooling is an explicit gap.
