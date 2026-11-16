---
name: monarchy-verify
description: Independently check a worker result against the exact brief, source and project gates. Use before accepting a handoff result or completion claim; a worker saying done is not verification.
---

# Monarchy Verify

## Inputs

- The brief, endpoint, task revision and claimed result.
- Exact source or artifact identity and native test, review and delivery evidence.
- Project-native verification skills, required environments and evidence reuse rules.

## Workflow

1. Turn the brief's endpoint into checkable claims. Bind every claim to the source, artifact or release it concerns. Separate implementation, review, merge, deployment and user-visible acceptance when the project does.
2. Use native verification and review workflows. Run the checks relevant to the changed behavior and required policy; do not manufacture tests that merely restate the implementation.
3. Read back actual outcomes. A command that started, a queued build or an agent summary is not a passing result. Mark unavailable, stale or mismatched evidence explicitly.
4. Ask an independent fresh-context reviewer to challenge consequential findings or acceptance claims when required or warranted. Give the reviewer the brief and evidence, not a preferred verdict. If no independent reviewer is available, state that limit.
5. Classify each claim as verified, failed or unknown with its evidence and revision. Reuse earlier evidence only under the project's stated rules and explain why its inputs still match.
6. Record the verdict and remaining work. A passing verification result enables completion review; it does not itself close the task or authorize delivery.

## Output

An evidence matrix for the requested endpoint, including source identity, checks, native results, review provenance and unresolved claims. See [the verification verdict](references/output.md).

Use the installed runtime's supported Python API or operator-controlled orchestration to update the canonical operational record. Do not invent commands or edit runtime storage directly. If persistence is unavailable, return a local draft marked `persisted: false`; do not create a competing source of truth.

## Authority

A verifier may perform checks authorized for the task. Verification is not permission to deploy, modify production, relax a gate or change the acceptance criteria. Use read-only evidence when the required execution would exceed the grant.

## Failure and no-op

Missing tooling, inaccessible environments, failing checks or stale revisions prevent a passing verdict for affected claims. Return unknown separately from failed. If the exact endpoint and revision already have sufficient valid evidence, reuse it explicitly rather than rerunning checks without a reason.

## Project overrides

Read the target project's instructions and `.agents/config.md` when present. Its native workflow, review and delivery skills govern project work. Use those skills before a generic fallback, and retain their paths and versions in the task. Overrides can narrow or refine this workflow; they cannot widen the user's authority. Missing optional config is fine. Missing required policy or tooling is an explicit gap.
