# Continuous Backlog

Continuous backlog work needs an owner-confirmed project grant. The recommended
cap of eight, twenty-minute idle interval and forty-eight-hour review are
configuration defaults. Loading them starts no work. A grant authorizes tracked
work within its project scope through preparation and review; it does not authorize merge,
production, spending, contact with people or other reserved actions.

The Secretary runs bounded reads and explicit dispatch commands. No scheduler
is installed, and a completed command does not keep supervision alive. See
[cadence](cadence.md) for bounded observation and waiting, and the
[design input](planning/continuous-backlog.md) for the wider target model.

## Grant an exact scope

`Backlog.propose(project, references=None, owner_message=..., builder_cap=...)`
creates a durable decision for tracked work in one repository. A project-wide
grant can cover new in-project issues without another activation box. An optional
allowlist restricts the grant to at most twenty exact issue or pull-request
references; each has `kind` (`issue` or `pull-request`) and `number`.
An allowlisted grant never silently becomes project-wide. The proposal freezes the scope, cap, configured
selection order and prepare-and-review endpoint, together with the current
configuration identity. Its cap cannot exceed `backlog.builder_cap`.

The Queen presents the proposal through the trusted owner interface. After the
actual answer is recorded, `apply(decision_id)` accepts only the exact
owner-origin confirmation. The proposal and its recommended option are not
activation. `state(project)` reads the resulting state; `revoke(project,
owner_message=...)` restricts it immediately. A replayed earlier confirmation
cannot restore revoked authority. The local API records authority supplied by
a trusted caller; it does not authenticate a human from a message reference.

An installation with pins binds the grant to its current project pin, effective
configuration and source identity. A pre-configuration installation explicitly
records `legacy-unpinned` qualification and freezes the defaults, effective
configuration and source digest available to that path. It still needs a new
actual owner activation. This compatibility path supplies no owner/project
source pin, native founding proof, profile-readback qualification or succession
proof. Adopting pins or changing the frozen policy requires a fresh applicable
grant rather than silently inheriting the old one.

The CLI uses the same private journal as the other runtime commands. A proposal
file can contain `{"project":"example/project","builder_cap":1}`; add
`references` only for an exact allowlist. Prepare the decision first:

```sh
python3 -m monarchy --state /private/royalty.db backlog propose /private/proposal.json --owner-message OWNER_REQUEST
```

After the actual owner box is answered, record the answer with its returned
decision ID, revision and genuine owner reference, then apply it:

```sh
python3 -m monarchy --state /private/royalty.db answer DECISION_ID /private/answer.json --revision REVISION --owner-message OWNER_REPLY
python3 -m monarchy --state /private/royalty.db backlog apply DECISION_ID
python3 -m monarchy --state /private/royalty.db backlog state example/project
```

Only an actual accepted proposal supplies `{"accept":true}`. A copied example,
operator guess, recommended option or a worker's message cannot supply that answer.

## Select without changing GitHub

`GitHubBacklog.read(project, references)` uses bounded, fixed read-only GraphQL
queries for an explicit window of at most twenty references. An allowlisted grant
restricts that window to its approved references; a project-wide grant permits
new tracked work in the same repository. The reader does not discover the whole
repository or write labels, comments, assignments, reviews or PR changes.
Incomplete dependency or linked-PR evidence holds the affected candidate.
Fork PRs hold rather than inheriting authority over another repository.
The read defaults to thirty seconds and cannot exceed sixty. Aggregate raw JSON
is capped at one MiB; normalized snapshots and candidates must fit the record
layer's sixty-four-KiB payload bound. A truncated relationship is not complete.

`select(snapshot, effective_config, classifications)` chooses the next eligible
item within that bounded window and returns per-item holds. The trusted Secretary
supplies the window; the result makes no whole-repository completeness claim.
The configured default order
is open PRs, wanted parked PRs, priority epics, user-reported bugs, other bugs,
then remaining work by priority and smallest size. Dependencies and current
ownership still apply. A smaller item cannot bypass an unmet dependency.

Classification is explicit trusted input bound to the source snapshot: bucket,
priority, size, wanted status, supplemental dependencies, ownership, an issue's
planned branch and the classification evidence reference. Unknown classification
holds. The selector does not infer authority or priority from arbitrary prose or
label names. Native dependency evidence cannot be removed by classification.

Candidates retain their bounded source, classification and policy identity,
including full source revision and case-preserved branch. Normalized snapshots
retain hashes instead of raw private titles and bodies. A new read checks that
the candidate is still current before preparation and admission. The receipt
must include an offset-aware observation time no more than sixty seconds old
at admission, and cannot come from the future. A caller-supplied timestamp is not
authentication of that read. `validate_frozen_candidate` checks retained binding
only; it cannot substitute for the fresh-read check.

`backlog read FILE` takes `project` and `references`. `backlog select SNAPSHOT
CLASSIFICATIONS` takes the resulting snapshot and a JSON list of classifications;
its result includes `candidate` and held items. Keep the candidate object itself
for `backlog bind TASK_FILE --candidate FILE --grant-id ID`. Binding prints the
task data without registering an assignment or dispatching work. Exports use
compact bounded JSON so a valid output remains within the input-document limit.

## Reserve before dispatch

`Backlog.bind(task_data, candidate, grant_id)` binds an assignment to its exact
candidate and grant. `prepare(task_id, candidate, fresh_snapshot,
idle_source=..., new_session=False)` prepares a dispatch; delivery remains the
separate runtime operation. Preparing an intent does not prove that a native
message was sent or that a builder started.

Capacity and writer custody are checked transactionally before external action.
Reservations bind repository, branch, task generation, native session, candidate,
grant and configuration. Prepared, in-flight and uncertain operations consume
capacity. An active grant's tighter cap also limits independently authorized
writers in that project; manual work cannot bypass the shared count. Without an
active grant, the configured cap still applies to writer admission.
A native idle status, completed model turn, expired interval or merged
PR does not free a reservation or prove that background processes stopped.

Release requires either a never-admitted cancellation or retained positive
stopped-process custody through `release(reservation_id, receipt_id, receipt)`.
Retain uncertain operations and reconcile their original identities. Do not
delete reservations, manufacture stopped evidence or dispatch a replacement
because readback is delayed. Pause, Stop, revocation, configuration drift and
changed candidate evidence hold new admission while preserving read-only
reconciliation.

Migration retains historical admitted non-Queen native operations unless they
were explicitly read-only. An unknown physical branch becomes
`legacy-unmapped` custody and holds new writers across that project. Multiple
old intents for one session remain separately retained. They are not free slots
or evidence of separate stopped processes. Reconciliation remains available;
release requires positive stopped-process evidence and no unresolved worker
operation for that task or session. Historical branchless prepared intents cannot
start new work.

A never-admitted release receipt is
`{"kind":"never-admitted","operation_id":"ORIGINAL_OPERATION_ID"}`. It
atomically fails that prepared operation before releasing custody, so a late
caller cannot start it. This receipt cannot release an admitted or legacy writer.

A stopped writer uses `{"kind":"writer-stopped","outcome_id":"STOPPED_OUTCOME_ID"}`.
The referenced outcome belongs to the exact task and retains this payload:

```json
{
  "kind": "writer-custody",
  "generation": 1,
  "session_id": "ACTUAL_WORKER_SESSION",
  "writer_repository": "example/project",
  "branch_ref": "refs/heads/work/item",
  "native_status": "idle",
  "processes_stopped": true,
  "background_work_clear": true,
  "observed_at": "ACTUAL_OFFSET_TIMESTAMP",
  "evidence_refs": ["ACTUAL_PROCESS_EVIDENCE"]
}
```

Use the actual identities and host evidence, never the placeholder values or an
idle reading alone. Legacy unknown-branch custody uses JSON `null` for
`branch_ref`. The stop observation must follow the most recent admitted worker
activity, including read-only work in the same session. Reconcile uncertain
operations for the same task or session first. These are trusted adapter assertions; the record
API neither kills processes nor authenticates the host evidence.

## Pull after observed idleness

The default twenty-minute interval uses actual retained cadence observations,
not an agent's estimate or the time a task record was created. `idle_source`
names `task_id`, `generation`, `first_observation_id` and `last_observation_id`.
Those observations may belong to the prior assignment for the same native
session; that relationship must be retained and checked.

Distinct observations must establish the full configured interval without
intervening working or unknown state, progress, or a named watched event.
Unknown native state is not idle. A watched event needs its retained source and
next check. An idle interval cannot be backdated or reused after a dispatch,
and it never releases capacity by itself.

At the qualifying observation, select and prepare the eligible authorized work
in the same bounded pass. Native delivery and the builder's actual report remain
separate receipts. The owner being away or having an open decision box does not
turn internal supervision into permission to send an owner-directed summary;
the conversation holds still apply.

`backlog pull TASK_FILE --classifications FILE --idle-source FILE` performs one
bounded read, selection and preparation pass. It sends nothing. The lower-level
`backlog prepare FILE --snapshot FILE [--idle-source FILE]` takes `task_id` and
`candidate` in its input file. Both support `--new-session`, subject to the
existing profile-creation limits. `prepare-dispatch` and `deliver` accept
`--backlog-snapshot` for backlog evidence; an uncertain original operation keeps
its read-only reconciliation path without a new candidate read or another send.

The normal CLI obtains a fresh GitHub read for new admission rather than treating
a saved snapshot file as proof of current state. The Python validation seam
still requires a trusted adapter to supply the real read. GitHub and the local
SQLite transaction cannot form one atomic remote snapshot.

## Review the trial

After the configured review interval, `review(project, metrics,
observed_at=..., source_refs=...)` prepares an owner decision bound to the exact
measurement snapshot. Present merged PRs per day, CI cost, review latency and
sign-off queue size, with their time window and sources. Missing telemetry is
unknown, not zero. A synthetic test clock is not a completed native trial.

Activation schedules one durable Secretary `backlog-review` check at the actual
activation time plus the frozen review interval. Bounded `due` and `wait` passes
retain that obligation; grant changes and normal admission holds remain visible.
Preparing the review box can complete this check only with
`{"decision_id":"REVIEW_DECISION_ID","decision_digest":"FULL_PAYLOAD_SHA256"}`
through `cadence complete`. The exact decision, grant, window and creation time
must match. This receipt proves preparation of the retained box, not its native
presentation, an owner answer or a capacity change.

Measurements describe retained project activity during the interval from the
actual activation to `observed_at`, with the end excluded. They do not establish
that the grant caused those results or that every measured PR came from a backlog
dispatch. Source collectors must state complete coverage explicitly.

| Metric key | Measurement |
| --- | --- |
| `throughput` | Distinct same-project merged PRs, with full revisions and merge times in the window, divided by elapsed days. |
| `ci_cost` | A bounded nonnegative decimal `amount` string and three-letter `currency`. |
| `review_latency` | Mean hours from ready to reviewed for distinct candidates whose two timestamps are inside the window. No completed reviews stays unknown. |
| `queue_size` | The count of distinct candidate IDs in the retained sign-off queue snapshot. |

`metrics` and `source_refs` contain all four keys. A source reference names an
immutable `outcome_id` and full payload `digest`; missing sources use JSON `null`
and require a null measurement. Each retained `backlog.metrics-source` outcome
binds metric, project, grant, window, observation time, external `source_ref`,
explicit Boolean `complete`, and `data`. The adapter must obtain the actual
measurements. The runtime validates and derives the submitted values from those
records; it does not fetch billing, authenticate a collector or infer coverage.

One stable review decision retains that exact window and evidence for the grant.
Replaying it cannot replace the measurement snapshot with different data.

The review records a decision about the observed results. It does not raise the
builder cap, expand tracked scope, renew a revoked grant or create merge
authority. Any wider grant needs its own exact owner confirmation.

`backlog review FILE` takes `project`, `metrics`, `observed_at` and `source_refs`.
`backlog release RESERVATION RECEIPT_FILE --receipt-id ID` records a supported
custody release. `backlog revoke PROJECT --owner-message ID` restricts the grant;
revocation does not prove running work stopped or release its reservations.

## Qualification boundary

The [native qualification](verification/continuous-backlog.md) observed one
owner-approved, read-only task selected from GitHub after a retained idle interval.
The original dispatch was reconciled after delayed readback, the worker returned
a result that matched the immutable source, and the temporary grant was revoked.
Independent host inspection confirmed that the task's foreground commands had
exited and no task background work remained; the reservation was then released.
Selected private evidence was archived and independently downloaded from the
exact archive commit; every retained file matched its size and SHA-256.

The exercise uses the explicit `legacy-unpinned` compatibility path. Its worker
returned a plain transcript result; it did not send a native report envelope.
It does not qualify source pinning, native founding, full profile readback,
leadership rotation, a native forty-eight-hour metrics trial, or unattended
operation. No other installation was migrated.
