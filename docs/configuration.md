# Configure a Court

Configuration chooses how the court behaves. It does not grant backlog work,
delegation, spending, production actions or contact with people. This phase adds
strict configuration, confirmed profiles, durable pins and standing orders.
Later phases implement conversation, delegation and continuous supervision.

## Four layers

| Layer | Source | Scope |
| --- | --- | --- |
| defaults | `monarchy/config.py` `KEYS` | Reusable recommendations and bounds |
| project | `.agents/monarchy.json` in a project repository | That project's facts and allowed restrictive limits |
| owner | `owner.json` in a private repository | Court preferences and private owner facts |
| overrides | Private court records | Allowlisted live restrictions |

Each key has explicit allowed homes. Replace values have a single writable home;
min takes the tightest limit; union adds safety restrictions. A project cannot
set court voice, profiles or another project's values. The invariant floor cannot
be removed. Keys are flat dotted names. Profile values are explicitly typed
objects; other arbitrary nested configuration is rejected. Files may contain a
`_why` map keyed by settings present in that file.

The schema has 53 keys, including reserved values consumed by later phases.
Inspect the executable `KEYS` table and `config show` for defaults. Unknown keys,
duplicates, nonfinite numbers, wrong types, wrong homes and out-of-bounds values
fail with safe diagnostics. Python 3.9's standard library is sufficient.

A minimal owner file:

```json
{"voice.zone":"UTC","_why":{"voice.zone":"Confirmed court timezone"}}
```

A minimal project file:

```json
{"project.repository":"example/project","project.required_checks":["unit"]}
```

Keep real account facts, protected workspace names and source mappings private.
Neither file may contain activation grants. Model profiles are recommendations
until the two founding confirmations have been recorded.

## Validate and preview without state

```sh
python3 -m monarchy config check /path/to/project/.agents/monarchy.json --layer project
python3 -m monarchy config check /path/to/private/owner.json --layer owner
python3 -m monarchy config show --owner /path/to/private/owner.json --project /path/to/project/.agents/monarchy.json
python3 -m monarchy config show reports.max_lines
python3 -m monarchy orders worker
```

These commands do not create a database, start an agent or install a hook. Preview
output includes values, contributing layers and `_why` provenance. Keep output
private when it contains owner data. Preview is not an approved configuration.

## Found and pin

Commit both files first. Fetch the project's default branch and ensure the local
`refs/remotes/origin/HEAD` identifies it. Project pins must be ancestors of that
branch, and `project.repository` must match the origin GitHub repository. Owner
pins also require a full commit object ID. The source reader never loads working
file bytes, follows a symbolic file, resolves a moving branch name or honors Git
replacement objects.

Run each command from a clean committed Monarchy checkout. Replace all uppercase
placeholders with actual values; a commit is a full 40- or 64-hex object ID.

```sh
python3 -m monarchy --state /path/to/private/court.db config founding \
  --owner-repo /path/to/private/profile --owner-commit OWNER_COMMIT \
  --project-repo /path/to/project --project-commit PROJECT_COMMIT
```

This returns two durable decisions: complete role profiles together, then timezone.
The Queen presents each separately through the trusted owner interface. The CLI
creates decision records; it does not open a native host decision box or establish
human identity. After an actual answer, save `{"accept":true}` or
`{"accept":false}` in a private file and record it through the existing `answer`
command with the returned decision ID and revision:

```sh
python3 -m monarchy --state /path/to/private/court.db answer DECISION_ID \
  /path/to/private/answer.json --revision REVISION --owner-message TRUSTED_OWNER_MESSAGE
```

Only a literal Boolean true accepts. A report, recommended default, numeric one
or merely supplied message reference is not a founding answer. The caller must
already have authenticated the owner through the host route. These local records
do not authenticate hostile processes sharing the operating-system account.

After both exact proposals are accepted, record the approved source pins:

```sh
python3 -m monarchy --state /path/to/private/court.db config pin \
  --owner-repo /path/to/private/profile --owner-commit OWNER_COMMIT \
  --project-repo /path/to/project --project-commit PROJECT_COMMIT \
  --owner-message TRUSTED_PIN_APPROVAL
python3 -m monarchy --state /path/to/private/court.db config show --project example/project
python3 -m monarchy --state /path/to/private/court.db orders worker --project example/project
```

Pins retain exact source bytes, commit/blob identities, SHA-256, toolkit revision,
effective-config digest, order hashes and approval reference. Successors can load
them without source checkouts or network access. `config show` reports drift;
new dispatch/admission holds until the configuration is approved again. Changed
project facts, removed checks, changed defaults/orders or owner sources require
an exact configuration-change decision returned by `config founding` before
re-pinning. A new project cannot silently restore an older court owner profile.
Profile and timezone answers are reused when their exact values are unchanged.

Changing the court owner source can put other project pins on hold. Re-pin them
against the newly approved owner source. Re-bind existing tasks with an explicit
assignment-generation change using the records API after reconciling uncertain
operations; never edit a retained brief or delete pending operations to pass a gate.

## Registration and standing orders

`register` requires an approved pin for its project. It fills a missing binding
profile from the confirmed role and rejects a conflicting supplied profile.
`metadata.profile_role` defaults to `worker`. The task retains the pin ID, exact
standing orders and their hash. Dispatch includes them with the unchanged
user-authored brief. Operation admission rechecks the current pin, profile,
orders integrity and pause/stop inside the journal transaction. Readback of an
already uncertain operation remains available while new actions are held.

Existing v1 databases migrate transactionally to v2 with `pins` and `overrides`.
Legacy explicitly bound courts remain recoverable before configuration adoption.
After a court adopts pins, legacy tasks need an approved configuration binding
before another external action. Pending decisions and uncertain operations survive
the migration.

Every order has a stable rule marker. The owner may omit named taste rules through
`orders.omit` and add bounded `orders.notes.queen`, `.secretary` or `.worker` notes.
Invariants cannot be omitted. Project values render as labeled, escaped JSON data,
not instruction text. Worker briefs exclude unrelated private leadership facts.
The renderer consumes forwarding/report limits and identical-failure limits;
mechanical forwarding, cadence and failure-policy automation arrive in later phases.

## Restrictive overrides

Only allowlisted restrictions are admitted in this phase. For example, save
`{"court.paused":true}` to a private file, then:

```sh
python3 -m monarchy --state /path/to/private/court.db config override court.paused \
  /path/to/private/pause.json --owner-message TRUSTED_OWNER_MESSAGE
```

Overrides belong to the court, not the current session. Min and union restrictions
accumulate without losing earlier restrictions, including court/project limits.
`--project example/project` accepts only project-scoped keys. Arbitrary model
changes, grants, false control values and removal of protected entries fail.
Confirmed resume and other widening owner verbs are a later conversation phase;
do not write around this restriction directly in SQLite.
