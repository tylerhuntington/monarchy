# Conversation contract qualification

Status: normal native journey qualified; cancellation/reopening pending.
Recorded 2026-11-22 Pacific. The normal journey ran Monarchy
`9028d82c02f8d4a8ea14c2ead512c0f0c75f72f6`; offline cancellation coverage and the
prepared reopening exercise use `3d5a1c7d173f2f9806938e16ddb1a85eb35a7efd`.
Sixteen P2 targets are mapped;
`preference.reopen-cancelled-box` remains `pending:P2`.
Exact native identities and transcript evidence stay in the private audit.

## Native observations

| Scenario | Status | Required evidence |
| --- | --- | --- |
| Approved Queen and Secretary profiles | Observed | Actual initial session configuration and result metadata confirmed the approved model, effort, and Fast Mode values. Absence of a field was not treated as proof. |
| Unknown and ordinary open prompt hold | Observed | The prepared forward retained its identity and performed no native send while each prompt hold applied. |
| Actual owner answer closes the same prompt | Observed | The real supported question returned the owner's Continue selection. The open at `2026-11-22T12:19:29-08:00` and close at `2026-11-22T12:39:37-08:00` used the same tool ID. |
| Original forward releases once | Observed | One native send at `2026-11-22T13:40:52-08:00`; delayed readback left the operation unknown. A fresh process reconciled it at `2026-11-22T13:41:20-08:00` with zero sends. A complete two-page, 165-event scan found exactly one matching message with the registered sender, destination, client identity, and text. |
| Native cancellation and next-turn reopening | Pending | Exact native cancellation becomes `unknown/native-cancelled`; a never-seen tool ID opens with `answer-required`; forwarding stays held. |
| Answer and release after a reopened prompt | Offline only | Regression coverage checks the matching answer clears the replacement hold. A separate native post-reopen answer/release cycle has not been observed. |

The plan's P2 native gate is the ordinary real-question hold/answer/release cycle.
The cancellation exercise separately qualifies reopening and the retained hold.
These are distinct observations; their combination does not claim a completed
native post-reopen answer/release cycle or prove who caused a cancellation.
The native journey used explicitly registered legacy bindings with no config
pins. It qualifies that compatibility path, not a native pinned-config founding
or succession exercise. No close was fabricated and no delivery was retried.

## Offline evidence and parity scope

The complete offline suite passed all 304 tests, and `git diff --check` passed.
A target marker alone does not prove its runtime behavior. The [parity checks](../../tests/test_parity.py)
reproduce numeric defaults, box bounds, verb classification, and rendered rules.
The behavior checks below cover the accompanying runtime contracts.

| Catalog sources | Policy or value target | Behavior evidence |
| --- | --- | --- |
| Box framing, one question, requested decisions, no prose decisions, bounded approval, and option bounds | Queen conversation rules | Rendered rules and optional box lint. These are instructions and structural checks, not an automatic semantic prose classifier or a grant. |
| Single owner conversation | `coordination.owner-channel` | [Forward route and sender checks](../../tests/test_conversation.py), with native sender/destination readback above. |
| Reopen cancelled box | `conversation.no-prose-decisions` | [Cancellation transitions and migration](../../tests/test_conversation.py), [strict native result recognition](../../tests/test_prompt_hooks.py), and [hook-to-CLI subprocess cycle](../../tests/test_conversation_cli.py). Native reopening remains a separate observation. |
| Forward journal and header | `invariant.one-writer`, `invariant.headers` | [Durable intent, hold, once-only delivery, stale callbacks, and uncertain reconciliation](../../tests/test_conversation.py). |
| Forward character lint | `invariant.config-custody` | [Additive config lists](../../tests/test_config.py) and [forward rejection](../../tests/test_conversation.py). |
| Abandoned minutes and known-open-only | `prompts.abandoned_minutes`, `invariant.prompt-state` | [Expiry, unknown, replay, cancellation obligation, and transaction guards](../../tests/test_conversation.py). |
| Opt-in hooks | `invariant.runtime-boundary` | [Snippet generation and bounded hook input](../../tests/test_prompt_hooks.py), [stateless settings command](../../tests/test_conversation_cli.py). No automatic installation. |
| Owner verbs, classification, and bearings lines | `invariant.verb-classification`, `voice.max_lines` | [Current-answer controls, replay, override custody, and output cap](../../tests/test_controls.py). These targets cover vocabulary, authority classification, and the cap. |

## Limits

Unknown prompt state holds indefinitely. Only ordinary known-open prompts may
expire; expiry neither writes closed nor answers a decision. Reopened cancelled
prompts carry a non-expiring obligation. Generic unknown removes permission to
reopen; this phase has no force-close or automatic ambiguity repair.

Owner controls retain their documented scope: away records availability, stop
blocks new admission, and handoff records an approved intent. They do not batch
traffic, cancel native processes, or transfer a role. Decisions returns a bounded
page, and bearings reports control state and counts. Hooks neither authenticate
owners nor persist answers or grant authority.

Hook failure, missing-callback, replay, uncertain-write, and migration checks are
offline evidence unless explicitly listed as native observations above. This
qualification does not establish unattended recovery, live preference freshness,
complete source inventory, any later phase, or migration of another project.
