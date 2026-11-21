# 0006: Continuous Building and Owner Judgment

Status: Recorded design input; amended by decision 0007
Pacific date: 2026-11-16
Amended: 2026-11-20

## Context

The owner requested a reusable operating model in which builders prepare useful
changes continuously within an authorized backlog, independent reviewers inspect
the result, and the Queen keeps owner decisions in one conversation. Private
source records remain outside this public repository.

The original input required an owner answer for every backlog PR. The accepted
direction now also supports delegated approval of eligible internal PRs,
category-specific delegation and timed follow-up for owner priorities. Decision
[0007](0007-opinionated-defaults-private-owner-profile.md) records the later
configuration decisions. No policy described here activates itself.

## Operating-model input

- Visible changes include an inline gallery of changed surfaces in application
  context and a walkthrough video, inspected during independent review.
- Twenty minutes idle without a watched event triggers a bounded backlog pull.
- Builders may proceed through already-tracked work within an explicit backlog
  grant; implementation uncertainty alone need not require another intake.
- The recommended initial cap is eight concurrent builders, with independent
  review and a capacity review after 48 hours.
- Owner decisions retain approve, reject and send-back outcomes. Internal PRs
  may instead receive Queen approval under a current category grant, after
  current-head verification, no unresolved findings and all required checks green.
- Delegation records ask, delegated or ask-again-later states and supports
  revocation. Delegated answers record their grant rather than owner provenance.
- Owner-priority follow-ups retain 15-minute checks, 30-minute incident follow-up
  and 60-minute proof deadlines, with project-supplied milestone/feed facts.

## Monarchy design response

Capture the [operating model](../planning/continuous-backlog.md) as a target for
implementation and qualification. The Queen remains the owner interface, the
Secretary coordinates the work, and builders/reviewers are 00 Agent assignments.

Keep source and evidence identity through review, presentation, answer and
delivery. Owner judgment, delegated authority, technical review, merge and
production approval remain distinct records. Defaults choose how; grants choose
whether authority-bearing behavior runs.

## What stays unchanged

Each project retains its policy, custody, delivery gates and authorization.
Installation grants no merge or production authority and starts no background
service, agent or hook. Existing court installations are not migrated. The
never-delegable floor and trusted owner route must be enforced in code as the
implementation phases land.

## Consequences

Backlog selection, evidence contracts, sign-off and delivery coordination require
implementation and native qualification. Until then, role documentation must
describe them as targets and retain the limits of the bounded current runtime.
