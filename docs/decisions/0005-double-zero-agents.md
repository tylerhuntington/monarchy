# 0005: 00 Agents

Status: Accepted naming decision
Pacific date: 2026-11-15
Tracking: [#20](https://github.com/tylerhuntington/monarchy/issues/20)

## Context

The owner asked to call the task-execution role **00 Agents**, with each name
prefixed by numeric `00-` and a word or phrase describing its work. The owner also
requested a casual README link to reputable coverage of the royal-spy origin story.

## Decision

Use Queen, Secretary and 00 Agents in current role descriptions. Name new task
sessions for their purpose: `00-tests`, `00-docs`, or `00-build-fix`. The runtime
uses the task ID by default; `metadata.agent_name` supplies a readable descriptor
when the ID is opaque. Spaces and punctuation become hyphens, letters become
lowercase, and an existing `00-` prefix is retained once.

Link the README to the Royal College of Physicians' discussion of the disputed
royal-spy legend. Do not present the claimed historical inspiration as established.
That qualification comes from source review, not from an owner assertion about
historical fact.

## What stays unchanged

The prefix adds no authority. Task briefs, owner decisions and project rules still
govern every action. The wire role `worker`, stored keys, native IDs and public
Python interfaces retain their existing meanings. Historical records keep the
terminology used when they were written.

An already-journaled launch keeps its original name and identity on retry. The
naming change does not relaunch agents or rewrite uncertain operations.

## Consequences

Current instructions and skill packages use the new public name. Package integrity
pins must be refreshed when their text changes. A session label remains a label;
coordination uses the durable task, assignment and native session identities.
