# What This Version Does

Monarchy is an initial standalone release of a supervised operating model.

| Included | Boundary |
| --- | --- |
| Queen, Secretary, and Worker instructions | Agents must follow them; they are not access controls. |
| Briefs, handoffs, and succession records | Transfers are supervised; no automatic election or stale-writer fence. |
| Per-task repository and session bindings | Multiple repositories can be observed; their policies stay separate. |
| Conductor session and GitHub PR observation | Does not verify test results, merge queues, deployment health, or completion. |
| Persistent local watch baseline | Survives command restarts if retained; doesn't survive losing the machine without a copy. |
| Conductor cloud operating guide | No installed hooks, daemon, automatic dispatch, or prompt-safe forwarding. |

The observer makes no model calls. It still polls external APIs. Reading a change
doesn't send a notification or wake an agent by itself.

The PISCES implementation has additional reporting, forwarding, hook, and delivery
integrations. Those remain in PISCES. This release neither replaces them nor carries
over their authority grants, credentials, model choices, staging limits, or
production permissions.

Private `.monarchy/` records need deliberate retention. On an ephemeral machine,
store necessary handoffs in an approved durable location before leaving. Public
Git history is not the place for private task state.

No production release, infrastructure change, model subscription, or personal
outreach is authorized by installing Monarchy. Those permissions belong to the
owner and each project.
