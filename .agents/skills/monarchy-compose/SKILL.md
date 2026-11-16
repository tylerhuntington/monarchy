---
name: monarchy-compose
description: Turn a ready Monarchy brief into bounded tasks with dependencies, ownership and evidence gates. Use before dispatch or when the work graph changes; defer domain planning to the target project.
---

# Monarchy Compose

## Inputs

- A ready brief, endpoint, authority and open decisions.
- Project-native planning skills and repository architecture evidence.
- Current work claims, capacity, model preferences and resource limits.

## Workflow

1. Run the project's planning workflow when one exists. Inspect the relevant code or sources before dividing work; a list of plausible tasks is not a plan.
2. Choose the smallest useful task graph. Give each task one outcome, one writer, its allowed files or resources, dependencies and a verifiable endpoint. Keep coupled edits with one owner.
3. Mark which tasks can run in parallel and which require another task's evidence. Resolve overlapping write scopes before dispatch; use an integrator where changes must meet.
4. Assign a role and required capabilities, not an invented runtime promise. Preserve owner-selected model and effort. Note costs, concurrency and deadlines only when known or explicitly bounded.
5. Include verification, review and integration as real work. Test the plan against failure: blocked dependency, stale policy, 00 agent loss and a changed requirement. Record how each returns to a decision or recovery path.
6. Save the graph and readiness checks. Dispatch only tasks whose dependencies, authority and required tools are satisfied.

## Output

A versioned task graph with ownership scopes, dependencies, entry conditions, completion evidence, reviewer or integration assignments and explicit holds. See [the task contract](references/output.md).

Use the installed runtime's supported Python API or operator-controlled orchestration to update the canonical operational record. Do not invent commands or edit runtime storage directly. If persistence is unavailable, return a local draft marked `persisted: false`; do not create a competing source of truth.

## Authority

The Queen approves the work graph within the owner's request; a Secretary may draft it. Planning does not grant delivery, infrastructure, outreach or cross-project authority. Project approval rules still gate the corresponding steps.

## Failure and no-op

An unknown interface, conflicting write claims or missing native planning requirement leaves the affected tasks held. Research can be a bounded task when already authorized. If a valid graph already covers the unchanged brief, return its reference and do not replan for appearance's sake.

## Project overrides

Read the target project's instructions and `.agents/config.md` when present. Its native workflow, review and delivery skills govern project work. Use those skills before a generic fallback, and retain their paths and versions in the task. Overrides can narrow or refine this workflow; they cannot widen the user's authority. Missing optional config is fine. Missing required policy or tooling is an explicit gap.
