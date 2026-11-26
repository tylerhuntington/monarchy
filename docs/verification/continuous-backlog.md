# Continuous Backlog Qualification

One bounded native backlog pull completed in an isolated Conductor installation
on 2026-11-26. An actual owner answer authorized one read-only repository
inspection with one existing builder. The worker completed that task, its result
matched the immutable source, and the trial grant was revoked. Independent
stopped-process evidence allowed the branch reservation to be released. Selected
private evidence was preserved and independently verified outside the scratch
workspace, completing the evidence prerequisite for archival.

The runtime was tested at `720b07540178edb769748175b9a8a9b9cc6417bf`.
The documentation-only head `a904a9eede21bb65a6e82d29bbc2c2829ccbe0cc`
retained the same runtime digest:
`2cea1288452f57319e3d387d2848f621934c10bf03cdceaa61d91667ebb86823`.
The inspected checkout was `c20c424b6a1b1c3026358e4ee0c6fb1439c714f9`.
Private records retain the exact native identities, question, answer, operation,
source reads and result. This document summarizes their scope without publishing
those records.

## Native observations

| Step | Result | What it establishes |
| --- | --- | --- |
| Owner activation | Observed | The actual native question and its matching answer authorized the exact one-task proposal and revision. The accepted answer was applied once to the retained proposal; setup confirmations were not substituted for activation. |
| Idle interval | Observed | Two retained native idle observations were 339,351.638542 seconds apart. The bounded transcript read found no intervening worker events after the retained cursor. The interval exceeded the configured twenty minutes; no clock was backdated. |
| Source selection | Observed | The bounded read-only GitHub adapter read the approved issue, retained its source and classification, then reread it for admission. The scope contained one candidate; this was not a full-backlog ranking exercise. |
| Branch custody and admission | Observed | The one-builder grant reserved the exact task branch before native delivery. The assignment was read-only but deliberately exercised the writer-reservation path. |
| Delivery and reconciliation | Observed | Initial delivery readback was delayed, leaving the original operation unknown. Read-only reconciliation confirmed that same operation and native message identity without creating another dispatch. |
| Worker result | Observed | The actual worker transcript reported the expected full checkout revision, branch, README hash and first heading, with a clean tracked tree. An independent read of the immutable Git blob matched the result. The worker reported only foreground reads and no background or external work. |
| Trial revocation | Observed | The grant was revoked after the result under the original trial's retirement scope. Revocation alone does not release writer custody. |
| Stopped-process custody | Observed | The Secretary independently inspected the completed native turn, process tree and listeners after admission. The task's command subprocesses had exited and no task background or external work remained. Provider processes remained resident and idle; they were not killed. The exact reservation was released, and a fresh journal read confirmed both released custody and revoked authority. |
| Private retention | Verified | An independent fetch of the exact private archive commit verified all 49 selected files (455,663 bytes) against their manifest sizes and SHA-256 values. Repository visibility was private before and after verification. SQLite recovery and integrity checks passed; raw transcript windows and credentials were excluded. |

The worker returned a plain transcript result. Correlating that result with the
original dispatch does not establish native `monarchy.report` envelope delivery,
`Court.ingest` or `accept_report`. A worker's statement that it stopped also does
not replace independent process evidence.

An earlier activation question was interrupted by a host shutdown without a
recorded answer or close; another attempt ended in a transport error. Their
history remains unresolved rather than being rewritten as answered. A later
fresh question received the actual accepted answer used for this trial. No live
question was running at the final inspection, but the earlier orphaned box's
Conductor UI state was not verified.

## Offline evidence and parity scope

All 489 standard-library tests passed at
`a904a9eede21bb65a6e82d29bbc2c2829ccbe0cc`, and `git diff --check`
passed. The final documentation and parity changes also passed all 489 tests
(34.148 seconds). The following tests cover behavior beyond the single native task.

| Contract | Evidence |
| --- | --- |
| Exact project grant and admission | [Backlog tests](../../tests/test_backlog.py) reject wrong-origin answers, changed policy, stale candidates and revoked authority. An earlier answer cannot restore a revoked grant. |
| Builder cap and one writer | The backlog tests cover concurrent final-slot reservations, canonical branch conflicts, independently authorized writers sharing the project cap, retained legacy custody, uncertain operations and stale stopped-process evidence. |
| Idle pull | The backlog tests reject short or unknown intervals, intervening work or watched events, and reuse of consumed idle evidence. |
| Read-only selection | [Selection tests](../../tests/test_backlog_selection.py) cover fixed GraphQL reads, complete dependency and ownership evidence, category/priority/size order, source changes, bounds and fresh admission receipts. |
| Forty-eight-hour review | [Metrics tests](../../tests/test_backlog_metrics.py) derive measurements from retained sources, preserve unknown telemetry, enforce the exact observation window and reject altered replay. Backlog tests bind the scheduled review to activation plus the configured interval. |
| Command behavior and policy values | [CLI tests](../../tests/test_backlog_cli.py) exercise the same bounded paths. [Parity tests](../../tests/test_parity.py) check rendered settings and the actual runtime vocabulary. |

The eight P5 catalog targets now map to the settings and bounded runtime rules
above. The remaining P3 writer-custody target maps to the combined admission,
migration, reconciliation and stopped-process release evidence. Private retention
remains a separate archival requirement. Target names alone are not runtime proof.

## Limits

This was a `legacy-unpinned` compatibility exercise. It does not qualify pinned
founding, native profile creation or complete profile readback, succession,
source-preference freshness, or migration of another project. The native adapter
still reported the agent type as unobserved, so it did not claim a verified full
profile.

One reserved worker does not demonstrate an eight-worker native load test.
Source tests establish the capacity and concurrency rejection paths. Branch
reservations govern journaled operations; they do not lock the host against
unjournaled external writes or kill processes.

The forty-eight-hour review is implemented and tested with retained fixture
measurements. This short native exercise did not run for forty-eight hours or
collect live billing, throughput, latency or sign-off queue telemetry. It neither
installs a scheduler nor establishes unattended supervision. Later phases remain
separate work.
