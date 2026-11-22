# Conversation and owner controls

The Secretary can journal a short summary for the Queen, then explicitly deliver
it through the registered native route. Nothing in this module starts a watcher,
installs hooks, answers a question, or authenticates an owner.

## Prepare and deliver a forward

Task metadata must retain `queen_binding` and `secretary_binding`. Each is a
native binding with `repo`, `workspace_id`, `session_id`, and `profile`, just like
the task's existing `binding`. After configuration adoption, leadership profiles
must match the confirmed role profiles. The outcome must belong to the current
assignment generation.

Save the summary as a UTF-8 text file without a header, then run:

```sh
python3 -m monarchy --state /path/to/private/court.db prepare-forward OUTCOME_ID /path/to/summary.txt
python3 -m monarchy --state /path/to/private/court.db deliver OPERATION_ID
```

The first command stores one immutable operation and message identity for the
outcome. Repeating it with identical text returns the same intent; changed text
conflicts. The outgoing message starts with `[secretary] `. Defaults limit the
complete message, including its header, to three lines and 900 characters.
Configured forbidden characters and control characters are rejected. Nothing
silently truncates obligations or consumes the source outcome.

Delivery must run in the registered Secretary's native session. The transport
checks `CONDUCTOR_SESSION_ID` before sending and retains native sender readback.
This context check prevents accidental misrouting; it does not authenticate an
owner. The native adapter still reports an unobserved agent type explicitly.

## Prompt observations and holds

The [opt-in observer](prompt-hooks.md) writes only session identity, tool-use ID,
state, timestamp, and a cancellation reason when applicable. Registration binds
the Queen session to task metadata. The v4 database migration adds a nullable
reason to the append-only prompt history; old unknown rows remain ambiguous.
To inspect a session:

```sh
python3 -m monarchy --state /path/to/private/court.db prompt status --session SESSION_ID
```

An absent or unknown state holds indefinitely. An ordinary known-open prompt holds until a
matching successful close or the configured abandonment limit, 60 minutes by
default. Expiry permits admission without pretending the question was answered
or writing a close. Future or malformed timestamps hold.

An exact native cancellation of the current open prompt records `unknown` with
reason `native-cancelled`, while keeping forwards held. The Queen can reopen the
unanswered decision on the next turn with a tool ID absent from the entire prompt
history. That fresh `open` carries reason `answer-required`; its hold cannot expire.
Only a matching successful answer clears it. Repeated cancellations keep the
obligation. The observer does not invoke the next question, compare its meaning,
or treat the eventual answer as approval for an operation. Native cancellation
and reopening remain unqualified until separately exercised on the host.

Otherwise, opening a second prompt while one is unresolved is rejected. An open replay is
accepted only for the same current open tool ID and never resets its age.
Stale closes and cancellations cannot clear a newer prompt. An ambiguous close
becomes generic unknown; replaying the earlier close cannot release it. Generic
unknown also removes permission to reopen after cancellation, and a later
cancellation cannot repair that ambiguity. Generic unknown observations require
operator investigation and fresh native evidence; this phase has no force-close
or automatic ambiguous-state repair command. Do not fabricate callbacks to pass
the gate. A cancellation without the exact observed native result cannot use the
reopening path. The trusted local CLI records observations; it does not authenticate
the owner or prove who caused a native cancellation.

Prompt-open and forward admission use the same SQLite write transaction. An
open prompt prevents admission; an in-flight or uncertain forward prevents a new
prompt from opening. Uncertain delivery remains read-only reconciliation of the
original identities, even during pause, prompt holds, or configuration drift.
Native hook delivery and UI behavior must be separately qualified on the host.

Native report summaries use the configured report caps, five lines and 1200
characters by default. Evidence stays separate from the summary and retains its
existing transport/record bounds. A rejected summary is not recorded or consumed.

## Owner controls

These commands require a trusted local caller. Message references record where
authority came from; a string supplied by a worker is not authority.

| Command | Effect |
| --- | --- |
| `control bearings` | Read a concise status within the confirmed owner line limit. |
| `control decisions` | Read a bounded page of pending decisions with a continuation indicator. |
| `control pause`, `control stop`, `control away` | Persist the named restriction immediately with `--owner-message`. |
| `control resume` | Propose clearing pause, stop, and away; no immediate expansion. |
| `control model FILE` | Propose the exact complete role profile in the JSON file. |
| `control handoff FILE` | Propose a leadership role and target native session; record intent only. |
| `control apply DECISION_ID` | Apply the exact current owner-approved proposal atomically. |

For example:

```sh
python3 -m monarchy --state /path/to/private/court.db control pause --owner-message OWNER_PAUSE
python3 -m monarchy --state /path/to/private/court.db control resume --owner-message OWNER_RESUME
python3 -m monarchy --state /path/to/private/court.db answer DECISION_ID /path/to/answer.json --revision 1 --owner-message OWNER_ANSWER
python3 -m monarchy --state /path/to/private/court.db control apply DECISION_ID
```

Only a real owner confirmation recorded as exactly `{"accept":true}` applies a
widening proposal. Numeric substitutes, changed proposals, new pins or intervening
overrides hold it for a fresh question. Applying the same receipt twice never
clears a later pause. Requests reuse the owner-message identity; changing the
request behind that identity conflicts. All CLI JSON rejects duplicate keys,
nonfinite numbers and unbounded structures.

The model file has exactly `role` and `profile`; the profile includes `agent`,
`model`, `effort`, and boolean `fast_mode`. Its approved receipt overlays the
effective configuration without rewriting baseline source pins. Existing task
bindings and standing orders must be explicitly refreshed before another action.
An offer to promote the standing choice to `owner.json` is retained, but the file
is not edited automatically. Profile readback and no-substitution rules still
apply. A handoff file has exactly `role` (`queen` or `secretary`) and `session_id`;
the receipt does not rotate or launch anything.

Pause and stop prevent new admissions; they do not cancel commands already
running. Away records availability for later scheduling policy. No control grants
delegation, production operations, infrastructure changes, spending, or outreach.
