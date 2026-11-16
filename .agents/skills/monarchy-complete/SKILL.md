---
name: monarchy-complete
description: Close an owned task only after its requested endpoint is verified, then report the result through the Queen. Use for completion review, not merely because a 00 agent is idle or a pull request merged.
---

# Monarchy Complete

## Inputs

- The current brief and endpoint, verified evidence matrix and exact result identity.
- Open decisions, dependencies, external operations and ownership claims.
- Project completion, retention and delivery rules; the established report route.

## Workflow

1. Compare the verified result with the current brief, including later steering. Check every required claim and distinguish any explicitly accepted limitation from an unresolved gap.
2. Reconcile pending decisions, reviews, dependencies and external writes. Resolve or explicitly supersede obsolete questions with evidence; never clear them just to reach a terminal state.
3. Confirm no unfinished operation still needs this task's writer. Keep custody of any remaining work or create an explicitly scoped follow-up under existing authority without disguising incompleteness.
4. Record completion through the canonical runtime only when the endpoint is satisfied. Save exact evidence and the result reference, then verify the record readback.
5. Send one concise completion packet to the Queen through the established route: what changed, what proves it, remaining accepted limits and any real decision. 00 Agents report to the Secretary; they do not open a second owner conversation.
6. Release the task claim only after completion and delivery obligations are accounted for. Keep durable records under the project's retention policy; cleanup and archiving require their own authority.

## Output

A completion receipt with the endpoint, evidence, canonical completion readback and Queen delivery state, or an explicit incomplete verdict listing remaining requirements. See [the completion receipt](references/output.md).

Use the installed runtime's supported Python API or operator-controlled orchestration to update the canonical operational record. Do not invent commands or edit runtime storage directly. If persistence is unavailable, return a local draft marked `persisted: false`; do not create a competing source of truth.

## Authority

The task owner completes work within its brief; the Queen reports to the user. A completion record does not grant deployment, publication, cleanup or outreach. Approval and factual completion stay separate, and the owner is not asked to repeat an approval already granted.

## Failure and no-op

A failed or unknown endpoint claim, unresolved required decision, uncertain write or failed persistence keeps the task incomplete. Delivery failure leaves the completion message pending without rerunning the work. Repeated completion events are no-ops only after confirming the same revision, endpoint and saved receipt.

## Project overrides

Read the target project's instructions and `.agents/config.md` when present. Its native workflow, review and delivery skills govern project work. Use those skills before a generic fallback, and retain their paths and versions in the task. Overrides can narrow or refine this workflow; they cannot widen the user's authority. Missing optional config is fine. Missing required policy or tooling is an explicit gap.
