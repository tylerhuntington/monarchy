# Run the Court in Conductor

Use one Monarchy cloud workspace for the Queen and Chamberlain, and one isolated
project workspace per independent task. Sequential stages can share a task
workspace after a verified handoff.

This guide uses the Conductor CLI. Check `conductor --help` and `conductor model`
on the host before dispatch. Local Mac workspaces require the app's own controls;
this CLI integration is for cloud workspaces.

## Establish the leadership

The owner starts the Queen. Under that assignment, the Queen creates a Chamberlain
session in the same Monarchy workspace, using an explicit chosen profile and a
message file containing its role instructions and the court's scope. Record both
native session IDs in `.monarchy/leadership.md` and have the Chamberlain verify
its assignment.

A new Queen or Chamberlain follows [succession](succession.md). Do not take over a
session because its title resembles a role, or supervise an existing workspace
without a direct assignment or an authorized handover.

## Send a complete assignment

In the Monarchy workspace, prepare `.monarchy/task.md` from
`templates/brief.md`. Include the contents of `roles/worker.md` and all needed
project references. A task workspace cannot assume access to the Monarchy
checkout or the Queen's conversation.

Record the intended task and create attempt in a private dispatch note before
running the command. The following shell variables must already hold the target
Conductor project ID, a unique task name, and the explicitly chosen agent, model,
and effort. From the Monarchy checkout:

```bash
conductor --json workspace create \
  --project-id "$PROJECT_ID" \
  --name "$TASK_NAME" \
  --session-name '01 Build' \
  --agent "$AGENT" --model "$MODEL" --effort "$EFFORT" \
  --message-file .monarchy/task.md
```

For a research assignment, use a research stage name. Add `--fast-mode` only when
that profile calls for it. Do not change a model or billing route after failure
without applicable authority.

The command creates a workspace and its first session. Retain the response's
identities. If the response is lost or uncertain, search before retrying:

```bash
conductor --json workspace list --name "$TASK_NAME" --limit 100
```

List results are paginated. Follow `hasMore` using `--offset` and inspect every
plausible match. Workspace creation is not idempotent; a missing first-page match
is not evidence that it failed.

With `WORKSPACE_ID` and `SESSION_ID` set to the recorded identities, read them back:

```bash
conductor --json workspace get "$WORKSPACE_ID"
conductor --json session get "$SESSION_ID"
conductor --json session status "$SESSION_ID"
```

Verify the repository, workspace/session relationship, actual profile fields,
and task scope before registering the task in `.monarchy/court.json`. Treat
missing profile fields as unobserved. Native title or model labels do not prove
billing entitlement or approval provenance.

## Move to the next stage

Complete the handoff through predecessor quiescence and successor assignment.
Keep the successor's first message limited to validation before writing. Prepare
`.monarchy/next-stage.md` with the role, brief, exact source, handoff, and checks.

Generate and retain new UUIDs for the session and initial message in the dispatch
note before creating the stage. With those values set as `NEXT_SESSION_ID` and
`NEXT_MESSAGE_ID`, run from the Monarchy checkout:

```bash
conductor --json session create \
  --workspace "$WORKSPACE_ID" \
  --name '02 Review' \
  --session-id "$NEXT_SESSION_ID" --message-id "$NEXT_MESSAGE_ID" \
  --agent "$AGENT" --model "$MODEL" --effort "$EFFORT" \
  --message-file .monarchy/next-stage.md
```

Add `--fast-mode` here too when the chosen stage profile calls for it.

After an uncertain result, inspect the recorded session ID before any retry;
reuse the same IDs for the same attempt. Verify the new session independently,
retain its acceptance, and update the watch register. A fresh review session
checks the exact current source, not a predecessor's assertion of correctness.

## Reports and decision prompts

Put the report destination in the brief. Prefer the project's existing durable
record for routine updates, subject to its publication rules. Agent-to-agent
messages must stay within the authorized court and task scope. They carry facts
and instructions within existing authority, not new owner approvals.

This release has no prompt-safe forwarding helper. Hold routine updates in the
shared private record while the Queen is asking the owner a question. Do not
claim that a sent message cannot interrupt that prompt. Missing or ambiguous
human provenance must not authorize expanded scope.

The [observer](observer.md) returns changes to the active caller; it doesn't
install a re-arm hook or wake a stopped agent. The Chamberlain must arrange the
next bounded check and report degraded or interrupted supervision.

## Retire a workspace

Follow the project's retention and archival rules. First verify the endpoint,
retain useful artifacts, settle outstanding processes and external actions, and
complete any succession. Native archival is a separate action requiring applicable
authority. A merged PR alone is not evidence that the workspace can be discarded.

Command reference: [Conductor workspaces and branches](https://conductor.build/docs/concepts/workspaces-and-branches).
