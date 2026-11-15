# Start a Court

Set up one conversation with the Queen, then give the court a small task in
Conductor cloud. Start with a read-only investigation: the result should come
back to the Queen without you coordinating the Workers.

You need Python 3.9 or later on macOS or Linux for the observer. Live observation
also needs the Conductor CLI with access to your cloud sessions. GitHub PR reads
need an authenticated `gh` CLI. Choose an agent and model you already have access
to; Monarchy supplies no subscription or model default.

## 1. Check the package

In a terminal, clone the repository and enter it:

```bash
git clone https://github.com/tylerhuntington/monarchy.git
cd monarchy
python3 bin/monarchy.py check --court examples/court.json
python3 -m unittest discover -s tests -v
```

The check command prints `"valid": true` with zero tasks. The tests should pass
without credentials or network access. This checks the package, not a live court.

## 2. Give the Queen a home

Open this repository in a dedicated **Conductor cloud workspace**. This workspace
holds the Queen and Secretary; project changes happen in separate task
workspaces. The cloud workspace has its own checkout, so run the remaining file
commands there, from its Monarchy root.

Create private working records from the templates:

```bash
mkdir -p .monarchy
cp examples/court.json .monarchy/court.json
cp templates/leadership.md .monarchy/leadership.md
```

These files are gitignored. On a disposable machine, retain important handoffs in
an approved durable location before the machine goes away.

Start your chosen agent in that workspace and give it this instruction:

> Act as the Queen using AGENTS.md and roles/queen.md. Establish this court for
> the project I specify. Keep a leadership record, use a Secretary for
> coordination, and follow each project's existing rules. Keep my requests,
> status updates, important decisions, and results in this conversation. Start
> with one read-only task. Ask for missing project or model choices before dispatch.

This authorizes setup of that court and the bounded task, not changes to every
repository the agent can access. The Queen records the project, model choices,
report route, and limits, then uses [the Conductor guide](conductor.md) to arrange
the Secretary and task session. Monarchy does not install a service or hooks.

## 3. Try one assignment

Give the Queen an outcome such as:

> In my project, find where CSV exports are built. Return a short explanation
> with file references. Do not change files or publish anything.

The Queen records the brief and endpoint. The Secretary sends a self-contained
assignment to a Worker, verifies its native workspace and session identities, and
adds its row to `.monarchy/court.json` using [the task format](observer.md#register-the-work).
The task's `repo` must match the native workspace's repository; the observer does
not check that association for you.

## 4. Get the result in the Queen's thread

Ask the Queen how the task is going. She should give you a concise status and any
choice that needs your input. Routine questions and follow-ups stay with the court.

When the Worker finishes, the Secretary checks the report and file references.
The Queen returns the explanation and evidence in your conversation. Check that
it answers the original request. You should not need to relay a report or ask a
second agent to pick up the work.

If the result is incomplete, tell the Queen what's missing. She routes the
follow-up through the court within the original assignment, or asks about any
new scope.

### Optional: inspect the machinery

To inspect the task yourself, run this from the Monarchy root in the cloud
workspace:

```bash
python3 bin/monarchy.py status --court .monarchy/court.json
```

You should see the task's session status with an empty `errors` list. An idle
status means the turn ended, not that the requested outcome passed.

To exercise recovery, ask the Queen to arrange a handoff to a fresh session.
The successor should recover the request and decisions from the records and
accept ownership through [the succession protocol](succession.md). This checks
how the court preserves your direction when an underlying session changes.

## Next

Use [the bounded watcher](observer.md#wait-for-a-change) for a longer task.
Add a build task with independent review once the first task returns a checked
result through the Queen.
Keep the [implementation limits](limits.md) visible when deciding how much
supervision to delegate.
