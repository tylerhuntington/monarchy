# Delegation and actual answering authority

Delegation records which decisions the Queen may answer within a project and
category. It does not merge a PR, launch work, call the question tool, or transfer
another installation's authority. Configuration chooses available categories
and adds restrictions; only an answered owner proposal enables a grant.

## Category state

Every category starts at `ask`. `delegated` permits only answers that satisfy its
current grant and every action check. `ask-again-later` retains owner control;
it does not schedule a timer or automatically display another question.

The built-in vocabulary is listed in the Queen's `delegation.taxonomy` standing
order. Project `delegation.categories` additions use union and do not themselves
grant authority. Project `delegation.never` can add restrictions to the immutable
floor: production approval or rollout, Terraform apply, IAM, secrets, spending,
contacting or naming people, and legal actions. The runtime checks actual action
classifications, not just a category label. Unknown or incomplete classification
holds the delegated path.

Project-added categories can use only canonical safe action IDs, with an exact
same-project/category owner-origin precedent covering the actions, scope and
answer. They cannot define new executable action kinds or exceptions. For example,
the backlog-cleanup category does not authorize contact with people; the actual
contacting/naming action remains prohibited.
The `approve-internal-pr` action is reserved to `internal-pr-approval`, so a custom
category cannot bypass that category's mandatory evidence gate.

The trusted local API is `Delegation(records)`:

| Method | Result |
| --- | --- |
| `categories(project)` | Read the category vocabulary for the project. |
| `state(project, category)` | Read the current category state and its recorded basis. |
| `propose(project, category, state, owner_message=..., precedents=...)` | Prepare an exact-state owner confirmation, without applying it. |
| `apply(decision_id)` | Apply the exact current owner-approved proposal. |
| `revoke(project, category, owner_message=...)` | Immediately return the category to ask. |
| `followup(owner_decision_id, owner_message=...)` | Prepare one three-state follow-up box from an eligible owner-origin answer and its exact precedent. |
| `answer(decision_id, answer, expected_revision=..., grant_id=..., current_head=...)` | Record a qualifying delegated answer with the actual grant identity. |

A proposal requests one specific state. Its box offers Confirm This State
(Recommended) or Keep Current State. Confirmation is exactly `{"accept": true}`
from the trusted owner route. A refusal does not select another state. To request
ask-again-later, prepare that exact state and obtain its confirmation.

A follow-up is different: one box offers delegated, ask and ask-again-later
directly. Its exact owner answer is `{"state": "delegated"}`, `{"state": "ask"}`
or `{"state": "ask-again-later"}`. Applying that answer records the chosen state
without a second confirmation box. A boolean confirmation cannot substitute for
the follow-up's state selection, and a state selection cannot substitute for an
explicit-state proposal's confirmation.

Precedents are references with `decision_id` and `revision`. A proposal freezes
their eligible owner-origin payload and answer, its project and category, current
configuration, and the category-state checkpoint. Changed inputs require a fresh
proposal. A replay cannot overwrite a later revocation or restore older authority.

The Queen presents returned decision data through the supported owner question
tool. Neither this API nor the CLI opens a native box automatically. A follow-up
cannot offer delegation of a floor action, turn a grant answer into an owner
precedent, or widen a previous answer's scope.

## Commands

Keep the journal and request files in a private directory outside the repository.
Inspect categories and state before preparing a change:

```sh
python3 -m monarchy --state /path/to/private/court.db delegation categories example/project
python3 -m monarchy --state /path/to/private/court.db delegation state example/project ci-rerun-at-approved-head
```

A proposal file contains exactly `project`, `category`, `state`, and `precedents`:

```json
{
  "project": "example/project",
  "category": "ci-rerun-at-approved-head",
  "state": "delegated",
  "precedents": [{"decision_id": "approved-check-retry", "revision": 1}]
}
```

The referenced precedent must already be an eligible recorded owner answer.
Prepare the proposal, present its returned box, and record the actual owner
confirmation through the existing `answer` command before applying it:

```sh
python3 -m monarchy --state /path/to/private/court.db delegation propose /path/to/private/proposal.json --owner-message TRUSTED_OWNER_REFERENCE
python3 -m monarchy --state /path/to/private/court.db answer DECISION_ID /path/to/private/confirmation.json --revision 1 --owner-message TRUSTED_OWNER_ANSWER
python3 -m monarchy --state /path/to/private/court.db delegation apply DECISION_ID
python3 -m monarchy --state /path/to/private/court.db delegation revoke example/project ci-rerun-at-approved-head --owner-message TRUSTED_OWNER_REFERENCE
```

For a category follow-up, first prepare its single three-state box. After the
owner chooses, save the exact state answer in a private file, record it, and apply:

```sh
python3 -m monarchy --state /path/to/private/court.db delegation followup OWNER_DECISION_ID --owner-message TRUSTED_OWNER_REFERENCE
python3 -m monarchy --state /path/to/private/court.db answer FOLLOWUP_ID /path/to/private/state-answer.json --revision 1 --owner-message TRUSTED_OWNER_ANSWER
python3 -m monarchy --state /path/to/private/court.db delegation apply FOLLOWUP_ID
```

To record a delegated answer, use a qualifying grant and the exact pending
decision revision. Internal approval additionally requires a fresh full head:

```sh
python3 -m monarchy --state /path/to/private/court.db delegation answer DECISION_ID /path/to/private/answer.json --revision 1 --grant-id GRANT_ID --current-head FULL_HEAD
python3 -m monarchy --state /path/to/private/court.db prepare-answer DECISION_ID --current-head FULL_HEAD
python3 -m monarchy --state /path/to/private/court.db deliver OPERATION_ID --current-head FULL_HEAD
```

`--current-head` is required for internal approval at both preparation and
delivery admission. Obtain it again from the trusted repository adapter; do not
reuse an old observation merely because the frozen candidate has that value.
Other categories do not require this argument. The commands record or relay the
answer; they do not approve or merge a PR in GitHub.
An already uncertain operation remains eligible for read-only reconciliation
without reacquiring a grant or admitting a new send.

## Record before relaying

An ordinary owner answer records `answered_by: owner`. A delegated answer records
`answered_by: grant:<id>` and does not masquerade as an owner message. It needs a
clear permitted precedent in the same project and category, complete permitted
action classification, no new risk, and no unresolved flag. An uncertain match
leaves the decision with the owner.
The action list, scope and answer must match the exact permitted owner precedent;
the runtime does not invent a similar answer from prose.

Classified decisions come from the trusted record API or an adapter. Their
`payload.delegation` supplies `category`, a bounded `actions` list, concrete
`scope`, and `classification_complete: true`. A delegated target also supplies
its exact `precedent` reference, `new_risk: false`, and `unresolved_flags: []`.
Internal approval adds the candidate described below. These are trusted factual
assertions to validate, not facts inferred from a worker's question. P3 has no
generic classification CLI, and native report ingestion does not silently add
delegation classification.

Profile and timezone confirmations, owner controls, delegation proposals, and
other owner-only decisions cannot be answered through a grant. Worker reports,
headers, source prose and unmarked native messages cannot create owner authority.
The local caller must obtain owner authority through the trusted route; stored
references and this API do not authenticate a person or isolate hostile processes
sharing the same operating-system account.

The answer and its provenance commit before any relay is prepared. Admission
rechecks the current grant, project, category, action and configuration. Revocation
therefore holds prepared grant-dependent work. An already uncertain native write
still uses read-only reconciliation of its original identities; revocation is not
permission to resend it.

## Internal PR approval

The `internal-pr-approval` category requires an independent verified outcome for
the current assignment and exact full head, no unresolved findings, and every
required project check completed successfully. Missing, stale, ambiguous or
unsuccessful required checks hold the decision. The candidate, review evidence,
project and configuration must retain their exact bindings.

The candidate has exactly `candidate_id`, `repository`, `source_revision`,
`generation`, `outcome_id`, and `outcome_digest`. The digest covers the complete
verified outcome payload using the runtime's canonical digest. Its task must be
bound to current approved configuration, and its reviewer must differ from the
assigned builder. The assignment's latest outcome must be this verification;
new reports must be triaged before approval.

The verified outcome's `evidence` has exactly `repository`, `candidate_id`,
`source_revision`, `findings`, and `checks`. Findings are an explicit empty list
or distinct objects containing `id` and `status: resolved`. Waived or unresolved
findings do not qualify. Each check contains `name`, `repository`,
`source_revision`, `status: completed`, and `conclusion: success`. Check names are
distinct, every row refers to the exact candidate head and repository, and every
configured required check appears. At least one required check must be configured;
every reported check must succeed, including additional checks.

A frozen candidate does not prove the repository's current head. A trusted
adapter supplies fresh head evidence at answer and admission; the validator does
not fetch GitHub or authenticate its caller. Visible work keeps its evidence
requirements, and a technical approval does not bypass project review, merge,
deployment or reserved-action gates.

## Limits and recovery

The runtime handles bounded record operations. It does not provide a scheduler,
automatic follow-up presentation, semantic risk classifier, GitHub approval or
merge executor. Retained precedent and grant references support later digest and
revocation work; they do not activate those later phases.

Task generations fence stale owners and uncertain effects for one task. That is
not a global branch lock across separate tasks. `authority.one-writer` remains
`pending:P3` until an explicit repository/branch admission contract is proved;
the final parity closure retains this remaining work.

Changing these standing orders changes their digest. Existing pinned installations
must follow the approved re-pin and rebind procedure; an update is not permission
to silently accept drift or activate a grant.
