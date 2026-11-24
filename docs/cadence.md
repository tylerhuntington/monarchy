# Bounded cadence and digests

Cadence records what needs another check and the evidence that settles it.
It does not keep a model running, send a steer, enable backlog work or grant an
external action. A Secretary or explicitly enabled supported hook must run each
bounded pass. Keep the database, roster and evidence in private storage.

## Due checks and receipts

The `Cadence(records)` API retains exact check identities across restarts.
`due(now=..., limit=100, project=..., offset=0)` lists a bounded page and recomputes
current hold reasons. `get(check_id)` reads one check. Neither operation completes it.
Checks retain their kind, recipient, task/generation or project scope, due time,
payload, state and exact completion receipt.

`complete(check_id, receipt_id, receipt, completed_at=...)` records a supported
receipt. A sweep names its observation; report and status checks name their
recorded event. An idle steer names the confirmed worker-directed `[steer]`
operation, concrete action and deadline. A blocker names its recorded outcome.
Preparing a message or a wake notice is not a completion receipt.

A reminder or digest completes only through its exact confirmed Queen forward.
Its retained source outcome supplies `generation`, `source_check` and kind
`cadence-reminder` or `cadence-digest`. A reminder also names `decision_id` and
`decision_revision`. A digest includes `census_id`, `census_digest`, `slots` and
`warnings` from its structured preview. Create these sources through the trusted
record API or an adapter; the due command does not invent them or send messages.

Admission rechecks the current check, calendar occurrence and source. A digest
must still match the current roster and observation projection. The transaction
retains the admitted operation and source binding before the send. Each check
allows one admission, including when that operation later fails; investigate the
existing receipt instead of admitting a blind retry. A second operation cannot
repeat an uncertain or confirmed delivery for the same check.
Later confirmation uses that frozen admission evidence, so a new assignment or
configuration cannot rewrite the original delivery. Read-only reconciliation
remains possible after a hold; it never admits another send.

The caller records observations through:

```python
cadence.observe(
    task_id, observation_id,
    generation=generation,
    observed_at=observed_at,
    native_status=native_status,
    watched_event=watched_event,
    report_expected_since=report_expected_since,
    progress_ref=progress_ref,
)
```

These are trusted adapter observations, not text inferred from a worker's claim.
An explicit report expectation can also be recorded with
`expect(task_id, expectation_id, generation=..., since=..., source_ref=...)`.
Record the expectation before its brief or steer. Do not treat a missing report
as proof that a failed attempt occurred.

The idle ladder uses distinct fresh observations: a concrete action and deadline,
a sharper steer, then a blocker. Advancing the ladder requires the previous
confirmed steer and its deadline, followed by a later observation. A named event
counts as waiting only when the observer actually covers it. Unknown or stale
status cannot become idle, and a changed status timestamp alone is not new
progress. The standing orders distinguish identical failures from actual repair
attempts without new evidence. Polls and missing reports cannot establish either
count. `failures.identical_limit` and `failures.no_progress_limit` supply the
agent's stop-and-diagnose policy. This runtime does not execute or count arbitrary
agent repair commands; rendering these values does not create a repair executor.

## Commands

Keep request and receipt files private. Every supplied timestamp includes its
ISO 8601 timezone offset; commands that accept an omitted current time use the
actual current UTC time.

```sh
python3 -m monarchy --state /path/to/private/court.db cadence observe /path/to/private/observation.json
python3 -m monarchy --state /path/to/private/court.db cadence expect /path/to/private/expectation.json
python3 -m monarchy --state /path/to/private/court.db due --project example/project --limit 100 --offset 0
python3 -m monarchy --state /path/to/private/court.db cadence get CHECK_ID
python3 -m monarchy --state /path/to/private/court.db cadence complete CHECK_ID /path/to/private/receipt.json --receipt-id RECEIPT_ID
python3 -m monarchy --state /path/to/private/court.db cadence census /path/to/private/census.json
python3 -m monarchy --state /path/to/private/court.db cadence digest example/project
```

Observation, expectation and census files contain the corresponding API fields.
Completion accepts the exact receipt shape for that check's kind. An input file
does not authenticate its caller or prove an observation occurred.

## Schedule and owner holds

The default intervals are sweep 30 minutes, report overdue 20 minutes, status 30
minutes and stale status 60 minutes. Daytime reminders run every 120 minutes;
the morning digest uses 06:57 in the confirmed `voice.zone`. Inspect `config show`
for the effective values and their provenance.

`cadence.reminder_start` and `cadence.reminder_end` define one increasing same-day
window in that zone. Start is inclusive and end exclusive. The owner confirmed
the 08:00 to 20:00 window in [decision 0009](decisions/0009-decision-reminder-window.md),
replacing the initial implementation assumption. Both clocks have the owner layer
as their writable home. With the default two-hour interval, reminder slots are
08:00, 10:00, 12:00, 14:00, 16:00 and 18:00 in the confirmed zone.
A missing daylight-saving clock time uses the first valid later minute; a repeated
time uses its first occurrence. Local date and slot identities prevent duplicate
calendar occurrences across restarts or the repeated clock hour.

Owner-directed reminders and digests follow the Queen's
[prompt policy](conversation.md) and the owner's away state. Unknown prompt state
holds indefinitely; the existing known-open abandonment rule remains separate.
These holds do not stop internal Secretary supervision. Pause,
Stop and configuration drift hold new actions. A held check remains visible;
elapsed time or listing it is not an acknowledgment or permission to send.
After any hold clears, recheck admission before preparing an external action.
Older reminder buckets and prior-day digests remain recorded but become obsolete;
clearing a long hold does not admit a burst of missed calendar occurrences.

## Builder census

`census(project, census_id, observed_at=..., authority_ref=..., slots=...)`
records an explicit roster and its source reference. Each slot has a `slot_id`
and status. An unassigned slot contains exactly `slot_id` and `status`, with
status `idle` or `unknown`. An assigned slot additionally requires `task_id`,
`generation` and `observation_id`; its status must match that retained observation.
`digest(project, now=...)` includes the observed state of those actual slots.
Missing, stale, superseded or uncertain observations remain unknown. This is a
structured preview, not delivery admission; inspect the check's current holds
and use the journaled forward path for any actual message.

The configured builder cap is a limit, not a roster. An authority reference is
supplied by the trusted caller; it does not authenticate the source or activate
builders. Preparing a census or digest creates no P5 backlog grant and launches
no session. Keep private identities and account facts out of public
status reports.

## Bounded wait and optional re-arm

`monarchy.rearm.wait` accepts the records, project and current Secretary session,
with a default 6600-second limit and 30-second polling interval. The hard wait
limit is 7200 seconds and polling is bounded from 1 to 60 seconds. It performs one
bounded wait. A timeout does not establish that supervision will continue.

`monarchy.rearm.settings_snippet(script_path, state_path, project,
secretary_session)` returns an opt-in Claude Stop/StopFailure configuration using
`asyncRewake`; the CLI prints that dictionary as JSON. Neither installs the
settings. The hook requires its explicit enable flag and a matching native
Secretary session; it is not a Queen hook.
Use only a host version that supports the documented hook contract.

```sh
python3 -m monarchy --state /path/to/private/court.db wait --project example/project --secretary-session SECRETARY_SESSION --max-seconds 6600 --poll-seconds 30
python3 -m monarchy rearm-settings --script /absolute/path/to/monarchy-rearm.py --state-path /path/to/private/court.db --project example/project --secretary-session SECRETARY_SESSION
```

The settings command prints a snippet without opening the database. Inspect and
explicitly install it through the host's normal configuration process only when
authorized. Merely printing it activates nothing.

A nonblocking lock permits one wait per journal and Secretary. The hook exits
without requesting a wake for a hold, timeout, error, foreign session or active
subagent/Stop hook context. Exit 2 requests a host wake only for a freshly eligible
prepared notice; safe errors disclose no private input.

A prepared notice durably records the wake attempt separately from the check's
completion. A crash or uncertain wake must not trigger an automatic repeat.
`cadence get CHECK_ID` exposes its `notification_intents` for recovery. Pending
checks stay visible for investigation and explicit disposition. Neither
a prepared notice nor a hook exit proves a native wake or message delivery.

Tests exercise local databases, fake clocks and process boundaries. They install
no live hook and make no native wake, send or unattended-operation claim.
