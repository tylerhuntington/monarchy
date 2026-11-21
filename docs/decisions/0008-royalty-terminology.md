# 0008: The royalty

Status: Accepted; maintained terminology backfill
Pacific date: 2026-11-21

## Context

Monarchy's maintained descriptions used an earlier collective name for the Queen,
Secretary and their agents. The owner selected "the royalty" and explicitly
requested that existing wording be updated, rather than applying the choice only
to new writing.

## Owner decision

Use **the royalty** for the collective in product prose. Apply plural agreement
when referring to its members: the royalty coordinate work and return results.
Backfill maintained documentation, role instructions, rendered orders, skills,
help text, diagnostics and authored descriptions. Use "installation" or "runtime"
when the sentence describes a software instance rather than the collective.

## What stays unchanged

Keep technical contracts such as `court_id`, `CourtRecords`, `Court`,
`court.paused`, `--court`, stored field names and existing paths. Preserve original
attachments, private historical evidence, immutable source identities and required
upstream attribution. Existing roles, authority, review gates and delivery rules
are unchanged. This naming decision migrates no PISCES installation and grants no
additional native, production or outreach authority.

## Consequences

New prose follows this vocabulary, and maintained surfaces receive the backfill.
Rendered-order and skill hashes change with their text and must be refreshed
through the existing pinning process. Historical identifiers remain usable;
renaming them would require a separate compatibility change.
