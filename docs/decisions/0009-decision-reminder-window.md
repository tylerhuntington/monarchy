# 0009: Decision Reminder Window

Status: Accepted; confirms existing defaults
Pacific date: 2026-11-23

## Context

The parity plan specifies two-hour daytime decision reminders but does not set
the daytime hours. The implementation initially used 08:00 to 20:00 as an
explicit assumption, with both clocks configurable in the owner layer.

## Owner decision

The owner selected the recommended 08:00 to 20:00 window for the royalty's
two-hour decision reminders. These hours are now confirmed preference rather
than an unresolved implementation assumption. Apply them in the confirmed
`voice.zone`; retain the installation's timezone and confirmation in its private
owner records.

## What stays unchanged

The existing defaults already match the selected hours. Scheduling keeps its
inclusive start and exclusive end, daylight-saving rules, prompt and Away holds,
and stale-reminder handling. This confirmation installs no scheduler or hook,
activates no backlog grant and migrates no existing installation.

## Consequences

Successors reuse the confirmed window without asking again. The private owner
profile records `cadence.reminder_start` as `08:00` and `cadence.reminder_end` as
`20:00` when that profile is prepared. Maintained documentation identifies this
as a confirmed choice; historical evidence of the earlier assumption is preserved.
