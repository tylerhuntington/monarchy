# 0002: One Conversation with the Queen

Status: Accepted
Pacific date: 2026-11-15

## Context

The initial Monarchy documentation led with continuity of context and ownership.
That explained handoffs but obscured the experience the framework is meant to
provide: one conversation at the top of the court.

## Owner decision

Emphasize a single user-facing Queen thread. The user directs work and follows
its progress there, while agents handle delegation and coordination behind the
scenes. Important decisions come back through the Queen with enough context to
answer. Adopt the single-interface philosophy illustrated by First Mate, using
original Monarchy prose.

Succession remains important as the mechanism supporting that relationship when
contexts or sessions change. It becomes supporting material rather than the
primary pitch. This refines the framing in [0001](0001-standalone-monarchy.md).

## What stays unchanged

Keep the required opening sentence, tagline, and current poster layout. The
existing roles, project authority boundaries, supervised execution, and runtime
limits remain in force. This decision doesn't implement a permanent chat,
automatic dispatch, or unattended recovery.

## Consequences

Lead the README and overview with one conversation, useful decisions, and results.
Make that experience the quickstart's first success condition. Keep operational
inspection and handoff checks available without making them the user's normal
coordination work.
