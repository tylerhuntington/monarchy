# Optional prompt hooks

The AskUserQuestion adapter records prompt observations for the current Queen.
Installation is explicit. Generating a snippet does not change Claude settings,
launch a session, or grant authority for the royalty. Until a native scratch
exercise succeeds on the intended host, this adapter is source-tested only.

## Generate settings for review

Run from the Monarchy checkout on the host that will execute the hook, with
Python 3.9 or later. Replace the example state path with the royalty's absolute
local SQLite path. Keep that path and the generated snippet private.

```bash
python3 - <<'PY'
import json
from pathlib import Path
from monarchy.prompt_hooks import settings_snippet

print(json.dumps(settings_snippet(
    Path('bin/monarchy-prompt-hook.py').resolve(),
    '/absolute/path/to/court.sqlite',
), indent=2))
PY
```

Review the result, preserve any existing hooks, then explicitly add it to the
Claude settings supported by the intended host. Do not put it in Conductor
repository settings or install it through a Monarchy setup script. The generated
command uses the current Python interpreter and absolute, shell-quoted paths.
It matches only the exact names `AskUserQuestion` and
`mcp__conductor__AskUserQuestion` and stays synchronous. The second name is
Conductor's namespaced question tool. Other namespaces, spelling variants,
prefixes and suffixes do not match.

The native environment must supply `CONDUCTOR_SESSION_ID` for the current Queen.
The snippet supplies `MONARCHY_STATE`. The adapter does not substitute Claude's
`session_id` for Conductor identity or permit inherited subagent calls.

The current [Claude hooks reference](https://code.claude.com/docs/en/hooks)
documents `tool_use_id` on these tool events. PreToolUse exit 2 blocks the tool;
post-hook exit 2 only reports an error after execution. The generated
`onFailure: "block"` also covers startup failures and timeouts and requires
Claude Code 2.1.295 or later. Qualify that behavior on the actual host before use.

## Observation contract

| Hook event or result | Recorded observation |
| --- | --- |
| PreToolUse for AskUserQuestion | `open` for this tool-use ID before permitting the tool |
| Built-in PostToolUse with matching questions and nonempty structured answers | `close` for this tool-use ID |
| Conductor PostToolUse with a recognized numbered answer for each input question | `close` for this tool-use ID |
| Conductor PostToolUse with the exact complete native cancellation result | `cancel` for this tool-use ID; forwarding stays held |
| PostToolUseFailure | `unknown` for this tool-use ID |
| Error, unrecognized cancellation, timeout, freeform dismissal, or ambiguous post result | `unknown` for this tool-use ID |

The [official tool output contract](https://code.claude.com/docs/en/agent-sdk/python)
provides structured `questions` and `answers`, optional freeform `response`, and
`afkTimeoutMs` for automatic resolution. The adapter accepts only the structured
answered form without an interruption or timeout marker. A prompt close is an
observation, never an owner decision or a grant.

The Conductor tool uses a separate positional format established by installed
source inspection: one text block starting with `User responses:` and a numbered
answer for each input question. Claude passes the content-block array to its post
hook; the exact single-content MCP envelope is also accepted. Single-line freeform
answers are valid, including Other responses outside the provided options.
Multi-select answers use indented bullet lines and require a multi-select input.
Partial cancellation prose, errors, extra blocks, incorrect numbering or answer counts,
empty answers, and ambiguous multiline freeform responses record `unknown`.
The adapter never interprets arbitrary JSON text as an answer. Source inspection
does not replace native hook qualification on the intended host.

Cancellation recognition requires the complete installed Conductor formatter,
including its `CONDUCTOR_ASK_USER_QUESTION_USER_CANCELLED` code, exact explanatory
lines, and the same strict content envelope. A prefix, interruption flag, timeout,
or failure event is insufficient. Native cancellation can result from steering,
shutdown, or interaction delivery failure as well as a UI cancellation; it does
not establish that the owner clicked Cancel. The observer retains only the state
reason, never the cancellation text or the question. This source-tested path
still needs a native cancellation and reopening exercise on the intended host.

Each observation invokes the existing runtime CLI using an argument array:

```text
python -m monarchy --state PATH prompt open|close|cancel|unknown --session SESSION_ID --prompt-id TOOL_USE_ID
```

The CLI checks the Queen session registered in task metadata, durable timestamps, matching IDs, and the
transaction excluding a forward already in flight or uncertain. A failed open
exits 2 and blocks the question. A failed close or cancellation write attempts one
same-ID generic `unknown` observation, then exits 2. If recording still fails, the adapter cannot promise
that an unknown state was saved; forwarding must remain held until reconciled.

Input is limited to 64 KiB. Duplicate keys and nonfinite JSON values are rejected.
Only the two environment settings above are read. The adapter never opens
transcripts, writes question or answer content, or displays native subprocess
output. Errors generated by the adapter are generic. Host startup errors can
still contain local paths, so keep host diagnostics private.

Claude documents that cancellation can omit the failure callback and can stop
post hooks. Managed post hooks can also receive failed tool output. Missing
callbacks therefore do not establish closed state. See the
[hook lifecycle reference](https://code.claude.com/docs/en/hooks#posttooluse).

An unknown prompt holds indefinitely. Only a cancellation matching the current
known-open ID records `unknown` with reason `native-cancelled`. That permits the
Queen to reopen the unanswered decision on the next turn with a never-seen tool
ID. The fresh open carries reason `answer-required`: forwarding stays held past
the abandonment limit until a matching successful answer closes that prompt.
Successive cancellations preserve this obligation. No observer invokes a new
question automatically, matches its semantic content, or grants authority.

An ordinary known-open prompt's admission hold can expire at the configured
abandoned-prompt limit; expiry does not store a close or answer a decision.
Generic unknown remains sticky, including after a previously observed
cancellation. A later cancellation or replayed close cannot repair it. Ambiguous
state requires operator investigation and fresh native evidence; this phase has
no force-close or automatic ambiguous-state repair command. The
[conversation contract](conversation.md) explains delivery and owner controls.

## Verify before enabling

Use scratch royalty records with explicit authority for its sessions and local settings.
Verify the current-holder identity, then open a real AskUserQuestion and observe
that a Secretary forward holds. Answer it and verify that the matching close
permits the held forward. Also cancel a question, verify the indefinite hold,
reopen the unanswered decision with a fresh ID, and answer it before verifying
release. Exercise a stale prompt ID,
a duplicate close after unknown, and an unavailable state file. Verify that an
unrecordable open blocks the native question and that an unknown result holds.
Test a missing script and hook timeout to confirm the host honors `onFailure`.
Restore the exact prior settings after the exercise. Synthetic fixtures alone
do not prove native hook delivery, cancellation behavior or forwarding races.

## Optional box lint

`lint_box(question, options)` checks one string question, two through four options,
the first label ending in `(Recommended)`, distinct labels, and bounded text.
Each option supplies `label` and `description`. It rejects multiple question
marks but cannot determine how many semantic questions prose contains. The
hook does not automatically run this optional style check. Framing before the
box and keeping decisions out of prose remain standing orders.
