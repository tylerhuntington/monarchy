---
name: monarchy-adopt
description: Adopt an existing project or workstream into Monarchy after an explicit owner handover. Use to establish custody and inventory live work without restarting or silently taking over other sessions.
---

# Monarchy Adopt

## Inputs

- The owner's handover scope and source, target project and existing lead.
- Existing task, session, branch, issue and review identities.
- Current native workflow, grants, pending decisions and active writes.

## Workflow

1. Verify that the handover names this project or workstream. Nearby workspaces are not part of the Queen's court by proximity.
2. Inventory existing leads, live sessions, worktrees, validation runs, open changes and decisions. Read native sources and label unreachable evidence as unknown.
3. Compare the inventory with the canonical task index. Preserve existing task identities and single-writer claims; map older records to the same task instead of forking them.
4. Agree the custody boundary with the existing lead through the authorized coordination route. Until an explicit handoff completes, the current writer remains the writer.
5. Record adopted scope, project policy references, current owners, authority limits, pending choices and the next check. Report gaps separately from the work that was successfully adopted.

## Output

An adoption receipt tying each in-scope workstream to its current owner, live evidence and policy references. State exactly which ownership transfers, if any, completed. See [the adoption receipt](references/output.md).

Use the installed runtime's supported Python API or operator-controlled orchestration to update the canonical operational record. Do not invent commands or edit runtime storage directly. If persistence is unavailable, return a local draft marked `persisted: false`; do not create a competing source of truth.

## Authority

Only the owner can hand a workstream to the Queen. Adoption does not authorize archiving unrelated sessions, changing their prompts, expanding grants or publishing private records. A lead may report facts without granting takeover.

## Failure and no-op

Conflicting leads, active unknown writes or inaccessible session state block ownership transfer. Keep the observed incumbent and ask for the missing evidence. A previously adopted, unchanged workstream is a no-op after checking its identity and current custody.

## Project overrides

Read the target project's instructions and `.agents/config.md` when present. Its native workflow, review and delivery skills govern project work. Use those skills before a generic fallback, and retain their paths and versions in the task. Overrides can narrow or refine this workflow; they cannot widen the user's authority. Missing optional config is fine. Missing required policy or tooling is an explicit gap.
