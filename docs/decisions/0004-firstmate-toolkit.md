# 0004: Adopt First Mate Machinery

Status: Accepted implementation direction; qualification remains explicit
Pacific date: 2026-11-15

## Decision

The owner requested implementation of the researched First Mate adoption plan,
with rigorous GitHub tracking in Monarchy. Build a full orchestration toolkit
around the Queen, Secretary, and Workers, beginning with the event-to-decision
loop and the core skill pack. Track work in epic #1 and its native sub-issues.

## Implementation choices

Preserve an immutable upstream distribution and its license. Verify its integrity
before extracting it into an isolated directory. Exercise real upstream machinery
before claiming compatibility. The first integration boundary is Conductor cloud:
separate worker filesystems, native identities, message readback, and a durable
royalty record. Ports at that boundary must state their reason and retain regression
coverage. Upstream internal names need not be renamed for the royal interface.

## What stays unchanged

Project instructions and authority remain local to each project. The Queen is the
single user conversation. No production rollout, personal outreach, takeover of
unrelated sessions, or automatic background installation follows from this work.
A test using a simulated transport is not native qualification. PISCES is not
migrated by this change.

## Consequences

The core may now include durable runtime and adapter modules in addition to the
observer. Every published capability needs tests and an honest implementation
boundary. Unqualified paths stay explicit, opt-in, and documented.
