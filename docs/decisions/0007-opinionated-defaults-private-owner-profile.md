# 0007: Opinionated Defaults and a Private Owner Profile

Status: Accepted direction; implementation, activation and migration remain separate
Pacific date: 2026-11-20

## Context

An existing agent installation has accumulated operating preferences across instructions,
configuration, decisions and runtime constants. Monarchy needs those capabilities
and a durable preference model without publishing private operational facts or
mistaking a default for authority.

Earlier documentation supplied no model defaults and described every backlog PR
as requiring owner sign-off. This decision updates that direction while retaining
explicit grants, project delivery gates and separate qualification.

## Owner decisions

1. **Stage adoption.** Monarchy reaches capability parity first. The existing
   royalty continue independently until side-by-side qualification. Migration is
   a separate later decision.
2. **Keep the owner profile private.** Owner facts and private values live in a
   private repository whose name is confirmed before creation. The public toolkit
   carries no private project issue links, personal identifiers, account names,
   protected workspace names or people's names.
3. **Ship the owner's preferences as defaults.** Remove private project
   identifiers. Reusable taste becomes toolkit behavior; project-specific facts
   and private owner values retain their separate homes.
4. **Confirm model defaults once at founding.** Show the proposed role profiles
   together in one owner box and record the answer. Successors reuse the confirmed
   profiles and never silently substitute a model.
5. **Use plain layer names:** defaults, project, owner and overrides.

## Configuration direction

Each key declares its allowed home. Defaults live in the toolkit; project facts
live in the project's pinned .agents/monarchy.json; owner facts live in private
owner.json; allowlisted live orders live in override records bound to the royalty.

Use strict JSON with flat dotted keys and an optional _why map. Numeric values
have hard bounds. Replace applies to single-home values, min chooses the tightest
limit, and union permits only additions to safety lists. Project settings apply
only to project tasks and cannot change behavior shared by the royalty.

Pin exact source bytes, full source commits, their SHA-256 digests, the approving
owner message, the Monarchy commit and effective configuration digest. Successors
load the same preferences offline. Changed defaults hold the royalty until re-pin;
rotation does not discard pause or other orders bound to the royalty.

Render role standing orders with stable rule identifiers and pin their output in
briefs and leadership records. Owner omissions cannot remove invariants. Render
project strings as labeled bounded data, never as instructions.

## Defaults choose how; grants choose whether

Defaults supply recommended behavior and recommended answers. Only an answered
owner box enables authority-bearing behavior, including role profiles, backlog
activation, internal-PR auto-approval and delegation-category states. Timezone is
also confirmed once at founding. Taste itself ships without repeated questions.

Eligible internal PRs may be approved under a current grant only after a verified
outcome at the current full head, no unresolved findings and all project required
checks green. Other reserved decisions remain with the owner. Record delegated
answers with grant provenance, never as owner answers.

The following must be enforced as invariants in code as the phases land: the never-delegable floor, restrictive
versus widening verbs, the trusted owner route, one writer, no silent model
substitution or metered fallback, the 00- naming prefix, message headers and the
rule that unknown prompt state holds.

The never-delegable floor covers production approval or rollout, Terraform apply,
IAM, secrets, spending, contacting or naming people and legal actions.

## What stays unchanged

This decision installs no hook, launches no agent, activates no backlog or
delegation grant and migrates no existing project. Project review and delivery
gates, protected actions, native qualification and owner control remain intact.
Model availability must be checked; unavailable confirmed profiles hold rather
than falling back. Production approval remains human-only.

## Consequences

Implement in dependency-ordered phases, with a sanitized parity map retaining
pending rows until each capability exists. Keep the private source mapping and
owner configuration outside the public toolkit. Update quickstart, decision
0006, maintainer instructions and implementation limits to match the accepted
direction without overstating installed behavior.

Completion requires parity proof, no unmapped newer owner preferences and a
side-by-side qualification plan. Actual migration still requires its own decision.
