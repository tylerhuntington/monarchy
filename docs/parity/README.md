# Parity Inventory

`pisces.json` contains sanitized target rows with source aliases, classification,
value and implementation target. Private source mappings remain outside this
repository. Owner and project values are setting names or descriptions here, not
real profiles or grants.

A `pending:Pn` row is unimplemented or unverified. A `dropped:` row explains an
explicit exclusion in the approved plan. Later phases replace pending targets
with `key:`, `rule:`, `invariant:` or `project:` only when their evidence exists.
Current rows are not proof of complete source coverage or live preference drift.

The public hygiene test scans maintained text, including first-party vendor
wrapper documentation. It preserves the pinned upstream archive and its legal
notice. Before publishing an amended private draft, also inspect every new
ancestor commit; a clean final tree cannot sanitize earlier commits.
