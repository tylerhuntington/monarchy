# First Mate Adoption

Implementation epic: [#1](https://github.com/tylerhuntington/monarchy/issues/1).
Milestone: [Qualification milestone](https://github.com/tylerhuntington/monarchy/milestone/1).

The acceptance loop is request → assignment → worker event → Secretary triage →
Queen decision → scoped answer → verified result. Queen, Secretary, and Workers
remain the only standing roles. The Secretary maps to First Mate's supervision
branch, not to its independently managed secondmate homes.

| Issue | Deliverable | Dependencies |
| --- | --- | --- |
| [#2](https://github.com/tylerhuntington/monarchy/issues/2) | Pinned upstream distribution and compatibility pilot | None |
| [#3](https://github.com/tylerhuntington/monarchy/issues/3) | Durable events, decisions, operations, acknowledgements | #2 |
| [#4](https://github.com/tylerhuntington/monarchy/issues/4) | Native Conductor transport | #3 |
| [#5](https://github.com/tylerhuntington/monarchy/issues/5) | Bounded Secretary supervision and Queen inbox | #3, #4 |
| [#6](https://github.com/tylerhuntington/monarchy/issues/6) | Twelve core skills and complete worker packages | #2 |
| [#7](https://github.com/tylerhuntington/monarchy/issues/7) | Integrated failure qualification | #5, #6 |
| [#8](https://github.com/tylerhuntington/monarchy/issues/8) | Native read-only Conductor qualification | #7 |

## Gates

All new runtime commands are explicit and opt-in. No setup hook installs or
starts them. Keep one canonical record of operational state. Never interpret a
worker's report as owner permission. Source integrity, isolated tests, and native
qualification are separate gates. Do not close the epic on offline tests alone.

Each implementation issue has a separate PR. Run the repository's offline suite
and whitespace check. Review the exact diff independently before merging. Issue
closeout records the PR, tests, and unverified boundaries. Preserve upstream
license and provenance in any copied material.

## Reuse boundary

First Mate is a bundled reference distribution and compatibility fixture, not
the engine behind Monarchy. Monarchy ports its coordination contracts into a
Python/SQLite runtime and a native Conductor adapter. The single database keeps
claims, decisions, outcomes and operation recovery together; running a second
upstream state store beside it would leave two sources of truth.

The source archive pins First Mate at
`427056c4181c41074ad24f051f79919330df0fa5`. It is an intact distribution, not an
advertised Python library. The first executable compatibility check uses its real
outcome store in a temporary operational home. Conductor is absent from the
upstream backend list at this revision. Cross-workspace delivery and trusted
owner input require an explicit adapter; installing the snapshot supplies neither.

The broader skill catalog is a roadmap. This milestone supplies the twelve core
skills first, selecting project-native methods for the actual coding work.

## Recovery and rollback

Installing this release changes no running installation. Revert an implementation PR to
remove its code. Retain private state before changing versions; never delete
unfinished operations to make a migration pass. Schema upgrades must be explicit
and tested. If native qualification fails, keep that issue and this epic open.

## Further design input

[Continuous backlog building and owner judgment](continuous-backlog.md) records
the next operating-model requirement. It builds on the bounded runtime without
changing this milestone's qualification claims. The backlog loop, visual evidence
pipeline, owner sign-off interface, and approval-bound merge coordination remain
separate implementation work.
