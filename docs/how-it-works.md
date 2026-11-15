# Meet the Court

Monarchy keeps the conversation with you separate from the work of coordinating
agents. Its royal vocabulary describes three jobs.

## The Queen keeps the promise

The Queen is your point of contact. You explain the outcome you want; she turns it
into an assignment with a clear finish line. She brings you results and decisions
that need your judgment. She doesn't edit project code while running the court.

A new Queen session inherits the role through [succession](succession.md), with
open decisions and existing authority intact. Starting a new chat alone doesn't
make it the Queen.

## The Chamberlain keeps things moving

The Chamberlain knows who owns each task, what they are doing next, and what must
happen before another agent takes over. Routine reports go here, so your
conversation with the Queen stays useful.

The name comes from the royal office that oversees household business and
coordinates its leadership. See the [Royal Household's description](https://www.royal.uk/sites/default/files/media/part1_introduction_to_head_of_state_expenditure_0809.pdf).
It's a working analogy: Monarchy's Chamberlain handles agent coordination.

The Chamberlain can resolve ordinary problems within the assignment. Changing the
scope, spending limits, or reserved actions goes back to you through the Queen.

## Workers do the work

Workers get a brief, an isolated task workspace, and a completion condition.
A small change can move straight to Build and then independent Review. Uncertain
work starts with Plan. Findings go through Fix and fresh Review before landing.

A reviewer checks the actual change and its evidence. If the source changes, the
review must cover the new source. A project may require more stages; Monarchy
follows that project's rules.

## Follow one task

Suppose you ask for a broken CSV export to be fixed and a PR prepared.

1. The Queen records the bug, the allowed scope, and “reviewed PR ready” as the endpoint.
2. The Chamberlain assigns a Worker and records its workspace and session.
3. The Worker reproduces the failure, fixes it, checks the result, and leaves a handoff.
4. After the Worker has stopped changing the branch, a fresh Worker reviews it.
5. The Chamberlain checks the evidence. The Queen gives you the PR and any remaining limits.

“PR ready” doesn't authorize deployment. A project with a different endpoint
keeps going until that endpoint is verified.

## Keep the record small

A task needs a brief, its current owner, a next action, and evidence. Put durable
results in the project's existing issue, PR, or approved record. Keep private
coordination notes in `.monarchy/` in the Monarchy home, with retention appropriate
to that machine. Never publish private transcripts to make a handoff convenient.

The [observer](observer.md) reads the task register and reports changes. An idle
session means “check the handoff,” not “declare success.”
