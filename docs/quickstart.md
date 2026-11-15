# Start a Court

Set up a Monarchy home, then try one supervised task in Conductor cloud. Start
with a read-only investigation so you can check the handoff before allowing changes.

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
holds the Queen and Chamberlain; project changes happen in separate task
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
> the project I specify. Keep a leadership record, use a Chamberlain for
> coordination, and follow each project's existing rules. Start with one
> read-only task. Ask for missing project or model choices before dispatch.

This authorizes setup of that court and the bounded task, not changes to every
repository the agent can access. The Queen records the project, model choices,
report route, and limits, then uses [the Conductor guide](conductor.md) to arrange
the Chamberlain and task session. Monarchy does not install a service or hooks.

## 3. Try one assignment

Give the Queen an outcome such as:

> In my project, find where CSV exports are built. Return a short explanation
> with file references. Do not change files or publish anything.

The Queen records the brief and endpoint. The Chamberlain sends a self-contained
assignment to a Worker, verifies its native workspace and session identities, and
adds its row to `.monarchy/court.json` using [the task format](observer.md#register-the-work).
The task's `repo` must match the native workspace's repository; the observer does
not check that association for you.

## 4. Check the handoff

From the Monarchy root in the cloud workspace, read the registered task:

```bash
python3 bin/monarchy.py status --court .monarchy/court.json
```

You should see that task's session status with an empty `errors` list. When its
turn ends, the Chamberlain reads the report and checks the file references before
the Queen returns the result. An idle status alone doesn't pass the task.

Ask the Queen to prepare a handoff to a fresh session. The successor must recover
the brief, result, outstanding work, and authority from the records, then accept
ownership through [the succession protocol](succession.md). If it needs you to
reconstruct the assignment, improve the handoff before adding more tasks.

## Next

Use [the bounded watcher](observer.md#wait-for-a-change) for a longer task.
Add a build task with independent review once the first handoff works.
Keep the [implementation limits](limits.md) visible when deciding how much
supervision to delegate.
