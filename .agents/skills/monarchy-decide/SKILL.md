---
name: monarchy-decide
description: Prepare, present and bind an owner decision to the exact task and question it resolves. Use for consequential choices or authority gaps; routine implementation choices belong with the 00 agent or Secretary.
---

# Monarchy Decide

## Inputs

- The blocked task, current revision and precise unresolved choice.
- Evidence, feasible options, recommended option and effects of waiting.
- Existing authorization, open prompts and the owner's actual answer when available.

## Workflow

1. Check whether the owner's prior instructions or project policy already settle this choice. Continue within that authority when they do; do not ask for the same permission again.
2. Build one concise question with options and a recommendation, the affected endpoint, what can continue, and what is held. Bind it to the task revision and a stable decision identity.
3. Persist the pending decision before presentation. Use the Queen's owner conversation and the runtime's supported delivery route. Merge overlapping questions and respect any verified open-prompt hold.
4. Record presentation separately from answer. Wait for an actual answer from the authorized owner; time elapsed, 00 agent agreement and a delivery receipt are not answers.
5. Match the answer to the exact question and current revision. If it is ambiguous or the choice materially changed, keep the decision open and clarify through the Queen. Preserve the original scope of the answer.
6. Persist the resolution and any standing policy through the target project's required decision workflow. Then separately release only the work covered by that answer. A resolved question does not finish the task.

## Output

A pending or resolved decision packet with its task, revision, question, options, answer source, scope and affected work. Report whether presentation, answer recording and work release each occurred. See [the decision packet](references/output.md).

Use the installed runtime's supported Python API or operator-controlled orchestration to update the canonical operational record. Do not invent commands or edit runtime storage directly. If persistence is unavailable, return a local draft marked `persisted: false`; do not create a competing source of truth.

## Authority

The Queen is the owner's decision interface. The Secretary can prepare packets but cannot invent or broaden an approval. No third-party contact, public naming, deployment or other controlled action follows unless the answer covers that exact action under project rules.

## Failure and no-op

Missing evidence, uncertain delivery or an ambiguous answer keeps the decision open. A previously resolved identical question is a no-op only while its revision and authority still apply. A task ending or a session expiring does not erase an unanswered question.

## Project overrides

Read the target project's instructions and `.agents/config.md` when present. Its native workflow, review and delivery skills govern project work. Use those skills before a generic fallback, and retain their paths and versions in the task. Overrides can narrow or refine this workflow; they cannot widen the user's authority. Missing optional config is fine. Missing required policy or tooling is an explicit gap.
