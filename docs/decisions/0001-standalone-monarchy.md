# 0001: A Standalone Monarchy

Status: Accepted direction; framing refined by [0002](0002-one-conversation.md), role naming updated by [0003](0003-secretary-role.md)
Pacific date: 2026-11-15

## Context

PISCES developed a Queen-led workflow for coordinating coding agents. Its
instructions and helper scripts mix general coordination with project-specific
policies. Moving between contexts and sessions also risks losing ownership,
decisions, and unfinished work.

## Owner decisions

Create a general orchestration project named **Monarchy**, hosted publicly at
`tylerhuntington/monarchy`, with the tagline **Keep Calm and DM the Queen.**
Use a monarchy metaphor and short, human-readable documentation. First Mate is
the reference for a single point of contact serving a group of coding agents.

The README opens with “The Queen is dead, long live the Queen.” Its purpose is
continuity of leadership and ownership through context and session transitions,
including graceful handoffs. The coordination role is **Secretary**, following
the naming update in [0003](0003-secretary-role.md).

The owner also requested a generated poster retaining the familiar red, white,
crown, and typography of “Keep Calm and Carry On,” with the wording changed to
“Keep Calm and DM the Queen.”

## Implementation choices

The initial release uses three roles, supervised succession, reusable records,
a Conductor cloud guide, and a small read-only observer. These are implementation
choices for a bounded first release, not claims that the owner approved an
unattended scheduler or a complete migration.

The observer is newly implemented. First Mate supplies conceptual inspiration;
its code and documentation are not copied into this repository.

## What stays unchanged

PISCES keeps its current orchestration installation and project-specific controls.
No production, infrastructure, spending, outreach, or live-session takeover
authority is granted here. Project review and delivery rules remain project-owned.

## Consequences

Monarchy can evolve independently of PISCES. A new session has an explicit
succession protocol and a place to recover its obligations. Mechanical ownership
enforcement, authenticated approval, automatic wakeups, and migration of existing
Monarchy installations require separate implementation and verification.
