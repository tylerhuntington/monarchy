# Parity Inventory

`pisces.json` contains sanitized target rows with source aliases, classification,
value and implementation target. Private source mappings remain outside this
repository. Owner and project values are setting names or descriptions here, not
real profiles or grants.

A `pending:Pn` row is unimplemented or unverified. A `dropped:` row explains an
explicit exclusion in the approved plan. Later phases replace pending targets
with `key:`, `rule:`, `invariant:` or `project:` only when their evidence exists.
Current rows are not proof of complete source coverage or live preference drift.

The [conversation qualification](../verification/conversation-contract.md)
separates P2's native observations from offline behavior checks and the narrower
scope of each target. A rendered invariant alone does not qualify a runtime row.

P3 maps 24 rows to the [delegation contract](../delegation.md). The executable
tests in `tests/test_delegation.py`, `tests/test_delegation_approval.py`,
`tests/test_approval.py`, and `tests/test_delegation_cli.py` cover owner-confirmed
grants, exact precedents, the immutable action floor, three-state follow-up,
revocation at admission, actual answer provenance, and source-bound internal
approval. The parity tests compare the catalog's category, state and floor values
with those runtime constraints. Taxonomy alone creates no grant.

The trusted-owner-route mapping has a limited meaning: native metadata
classification never creates owner authority, and grant answers cannot become
owner answers or owner-only confirmations. The transport and delegation tests
exercise those boundaries. The local owner route, action classification, current
head and review evidence still require trusted callers; these tests do not
authenticate a person or verify GitHub remotely. No native P3 exercise is claimed.

`authority.one-writer` remains `pending:P3`. Current ownership fences one task
and generation; it does not enforce shared branch custody across distinct tasks.
That gap must close before final zero-pending qualification.

P4 maps 11 rows to the [cadence contract](../cadence.md), including seven setting
values, three standing-order rules and the non-omittable check-custody invariant.
`tests/test_cadence.py` covers durable identities and receipts, source-bound
delivery admission, retained uncertain attempts, current report/observation
evidence, calendar occurrences and explicit census coverage.
`tests/test_rearm.py` and `tests/test_cadence_cli.py` exercise bounded waits,
process persistence, owner holds and internal Secretary supervision without
installing a hook or calling a native service.

The no-progress key proves the default and rendered stop policy, as the earlier
identical-failure key does. Neither mapping claims that Monarchy executes or
counts arbitrary agent repairs. Re-arm is opt-in and depends on a supported
host; a prepared notice is an attempt, not confirmed delivery or completion.
There is no native P4 or unattended-operation qualification claim. Reminder
window hours are documented implementation defaults, not recovered private
source facts. P5 through P10 rows retain their existing targets, and the inventory
still makes no full-source or live preference-drift claim.

The public hygiene test scans maintained text, including first-party vendor
wrapper documentation. It preserves the pinned upstream archive and its legal
notice. Before publishing an amended private draft, also inspect every new
ancestor commit; a clean final tree cannot sanitize earlier commits.
