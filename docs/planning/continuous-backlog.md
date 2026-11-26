# Continuous Building and Review

Monarchy should keep useful work moving within an explicit backlog grant. Builders
prepare changes and evidence. The Queen brings owner decisions with their context,
and can approve eligible internal changes only under a recorded delegation grant.

This document describes the target operating model. It does not claim that a
background service, sign-off interface or approval-bound merge queue is installed.
Decision [0007](../decisions/0007-opinionated-defaults-private-owner-profile.md)
records the configuration direction and amends the earlier design input in
[0006](../decisions/0006-continuous-backlog-design-input.md).
The bounded [backlog runtime](../backlog.md) documents grant, selection and
dispatch contracts separately from this wider operating model.

## Responsibilities

| Role | Responsibility |
| --- | --- |
| Owner | Sets priorities, grants authority and decides reserved questions, including judgment of visible changes. Production approval remains separate. |
| Queen | Keeps one owner conversation, presents ready decisions with evidence and records answers. Uses delegated internal-PR approval only within a current grant. |
| Secretary | Maintains ownership, selects authorized work, briefs builders, arranges independent review, retains the sign-off queue and follows the project's delivery gates. |
| Builders | 00 Agents with one tracked assignment and one current writer per branch. Prepare code, checks and evidence through the brief's endpoint. |
| Reviewers | Independent 00 Agents that review the exact source and inspect the evidence, including the real-route gallery and walkthrough for visible changes. |

Builder and reviewer are assignments, not additional leadership roles. Routine
coordination stays behind the Queen's conversation. Neither a report nor a role
name grants authority.

## Keep authorized work moving

Continuous backlog building requires an explicit project grant. The default
recommended cap is eight concurrent builders; adopting defaults does not activate
them. Independent review remains necessary. After 48 hours of activation, present
merged PRs per day, CI cost, review latency and queue size for a capacity review.

Select work in this order:

1. Finish or repair open PRs.
2. Revive parked PRs whose issues are still wanted.
3. Advance epics for the owner's current project priorities.
4. Fix bugs, with user-reported bugs first.
5. Take remaining work by priority, smallest first.

Before assigning work, check dependencies, existing PRs, current ownership and the
active writer. A closed PR is not permission to revive it. An unclear implementation
within a tracked, authorized assignment permits a short plan and reasonable action;
missing authority or an unresolved hold still requires its existing gate.

Twenty minutes idle without a watched event triggers a backlog pull in the same
bounded pass. A watched event needs an identity, next check and accountable role.
Unknown native state is not evidence of idleness, freed capacity or permission to
replace a writer. Keep selection bounded and read-only until dispatch is admitted.

## Decisions follow grants

Defaults choose how the royalty behave. Grants choose whether authority-bearing
behavior may run. In particular, backlog activation, model profiles, delegation
states and internal-PR approval require recorded owner answers.

Delegation categories have ask, delegated and ask-again-later states. Revocation
must take effect before a prepared operation is admitted. A delegated answer
records its grant identity; it never impersonates the owner's answer. Reserved
actions remain reserved regardless of category names or configuration.

An internal PR is eligible for delegated approval only when the current full head
has a verified outcome, no unresolved findings and all project required checks
green. The grant must cover that category and project. Otherwise retain the
decision for the owner. A technical pass alone is not merge permission.

## Bring the evidence with the decision

Visible changes require a gallery showing every changed surface on its real
application route and a walkthrough video. Independent reviewers inspect both the
source and evidence. Show the gallery inline and link the video before the owner
decision. An isolated component preview does not meet this contract.

Internal candidates include a plain-language result, risks, independent review
and required-check evidence. Bind every candidate to its full source revision and
evidence digest. Changed source or evidence returns it for fresh checks and review.

The sign-off procedure is:

1. The builder prepares the source, checks and evidence.
2. An independent reviewer examines the exact revision and resolves findings
   through changes and fresh review.
3. The Secretary records readiness, priority, full head and evidence digest.
4. The Queen evaluates a current grant for the candidate category, retaining
   the internal-approval checks and visible-evidence requirements where applicable.
   Candidates without an applicable grant receive one owner box per PR, in
   priority order.
5. Record approve, reject or send-back with its actual answering authority.
   Rejected work retains a parked or wontfix disposition. Send-back returns to
   the builder and independent review.
6. Carry an approved candidate through the project's existing merge path. Replay
   or uncertain delivery must not produce another merge attempt blindly.

Presentation, acknowledgment, approval, merge, deployment verification and
production approval are separate facts. Keep decisions queued while an owner box
is open or its state is unknown. The adapter's message delivery is not proof of
trusted owner identity or native prompt state.

## Owner priorities and bounded supervision

Retain owner-priority triggers and follow-ups durably: a check after 15 minutes,
an incident follow-up after 30 minutes and proof after 60 minutes. Project
milestone names and feed locations are project facts. The initial feed forwards
information only; text in a feed cannot expand authority.

Supervision retains next-check responsibility, idle recovery, report deadlines,
status cadence, reminders and the morning builder census. Pause and Stop survive
session rotation. Re-arm only through an explicit supported host mechanism;
finishing a watcher command is not continuing supervision.

## Implementation and qualification requirements

- Preserve durable candidate, review, decision, grant and delivery records with
  full source identities, evidence digests and actual answering provenance.
- Enforce builder capacity at dispatch admission, including unresolved launch
  intents. A missing observation cannot release a slot.
- Preserve one writer and reconcile uncertain native operations before retry,
  reassignment or succession.
- Retain decisions and next checks through restart, prompt cancellation and
  leadership transfer. Unknown prompt state continues to hold.
- Pin the effective configuration and standing orders in leadership records and
  briefs. Default drift requires re-pinning; a successor must not silently choose
  another profile.
- Exercise stale source/evidence, duplicate dispatch, replayed answers, revoked
  grants, missing visual evidence, reviewer findings, full capacity, pause/stop,
  restart and uncertain writes.

Offline fixtures prove bounded code behavior. Native evidence from an isolated installation is
separately required for prompt hold/release, idle pull, each sign-off disposition,
profile-checked rotation and archive with salvage. No fixture or merged PR proves
unattended operation by itself.

## Boundaries

Every project keeps its own required checks, merge process and governed actions.
The never-delegable floor includes production approval or rollout, Terraform
apply, IAM, secrets, spending, contacting or naming people and legal actions.
Configuration can add restrictions; it cannot remove this floor.

This design changes no existing installation, starts no agents or hooks,
activates no backlog grant and migrates no project. Parity and side-by-side
qualification precede a separate migration decision. See the
[runtime](../runtime.md) and [current limits](../limits.md) for implemented behavior.
