---
name: monarchy-recover
description: Diagnose a lost 00 agent, stale claim, stuck wake or uncertain external write and restore safe progress. Use after failed evidence or transport checks; recovery starts with reconciliation, not a blind restart.
---

# Monarchy Recover

## Inputs

- The affected task, latest checkpoint, ownership record and failure evidence.
- Runtime session and tool state, external operation identifiers and delivery receipts.
- Authorized retry limits, project recovery workflows and pending decisions.

## Workflow

1. Classify the failure from native evidence: live but quiet, waiting for validation, waiting for a decision, dead session, unreachable transport, stale claim, or unknown external write. Keep uncertainty visible.
2. Reconcile each attempted external write by its operation identity and observable result before retrying. A timeout is not evidence that nothing happened.
3. Check writer custody independently of lease expiry. Use the supported runtime to establish whether old work is stopped or safely isolated. Keep a replacement from touching conflicting resources until this is known.
4. Choose the smallest authorized repair: resume the existing 00 agent, redeliver an unacknowledged item, renew a valid claim, adopt settled output, or prepare a successor handoff. Use project-native recovery procedures and shared retry limits.
5. Perform one bounded recovery action, then read back its effect. On repeated identical failures, stop that retry sequence and bring a concrete blocker or decision to the Queen through the Secretary.
6. Save the diagnosis, action, evidence and next check. Do not close open owner decisions or claim completion as a side effect of recovery.

## Output

A recovery receipt stating the failure class, reconciled outcomes, custody, bounded action and verified postcondition. Unknowns and exhausted retry limits remain explicit. See [the recovery receipt](references/output.md).

Use the installed runtime's supported Python API or operator-controlled orchestration to update the canonical operational record. Do not invent commands or edit runtime storage directly. If persistence is unavailable, return a local draft marked `persisted: false`; do not create a competing source of truth.

## Authority

Recovery uses the original task's authority and existing retry limits. It does not grant destructive cleanup, new infrastructure, production access or contact with people. A Secretary can coordinate repairs within its assignment; consequential new choices go to the Queen.

## Failure and no-op

Unavailable native evidence leaves state unknown. If a repair cannot be verified, retain its identity and stop blind repetition. A healthy task is a recovery no-op only after live evidence disproves the reported failure; an expired lease alone never proves the task is dead.

## Project overrides

Load the approved project configuration from its pinned .agents/monarchy.json,
alongside .agents/config.md. Carry the installed Monarchy runtime's rendered
role orders, their SHA-256 and the effective configuration pin into the brief
and handoff. Verify the retained bytes, not a moving working-tree copy. Hold on
missing pins or drift. Owner notes and project data never relax invariants or
grant authority; founding confirmations remain separate.

Read the target project's instructions and `.agents/config.md` when present. Its native workflow, review and delivery skills govern project work. Use those skills before a generic fallback, and retain their paths and versions in the task. Overrides can narrow or refine this workflow; they cannot widen the user's authority. Missing optional config is fine. Missing required policy or tooling is an explicit gap.
