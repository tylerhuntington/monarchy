# Monarchy

The Queen is dead, long live the Queen.

A coding session ends. Its responsibilities shouldn't. Monarchy is an orchestration
layer for passing leadership, ownership, and unfinished work between agents without
making you rebuild the context every time. The next session should know what was
promised, what happened, and what it owns now.

<p align="center">
  <img src="assets/keep-calm-and-dm-the-queen.png" width="300" alt="A red poster with a white crown and the words Keep Calm and DM the Queen.">
</p>

## One conversation. A working court.

You talk to the **Queen**. The **Chamberlain** coordinates the work. **Workers**
build, investigate, and review in their own task workspaces.

| Role | What they do |
| --- | --- |
| Queen | Understand your request, keep the decisions straight, and bring back the result. |
| Chamberlain | Track ownership, watch progress, resolve routine blockers, and arrange handoffs. |
| Workers | Finish a bounded assignment and leave evidence the next agent can use. |

The crown belongs to the role, not the chat window. When a session fills up,
crashes, or hands over, its successor inherits a written record of the work and
its limits. A handoff is complete when the successor checks that record and
accepts responsibility. [How succession works →](docs/succession.md)

## Why we built it

Parallel agents gave us more hands and more coordination work. Someone still had
to remember which agent owned a fix, carry decisions between tabs, and notice when
an apparently finished task had stopped short of its goal.

Monarchy grew out of that work on PISCES. It keeps the useful parts: one conversation,
clear assignments, independent review, and careful transfers of ownership. Each
project keeps its own build, review, merge, and deployment rules.

[First Mate](https://github.com/kunchenguid/firstmate) inspired the single point of
contact. Monarchy puts continuity of leadership at the center of that idea.

## Start a court

Clone this repository and follow [the quickstart](docs/quickstart.md). Start with
one project and one task. Add parallel work when you can track its ownership.

This first version contains agent instructions, reusable briefs and handoffs,
a Conductor guide, and a Python status watcher. The workflow is supervised:
agents use the host's tools, and the watcher reads session and PR state. It does
not launch agents, transfer authority, or keep itself running after its host exits.

The instructions are project-independent. **Conductor cloud is the first runtime
integration**; other runtimes need their own integration and verification. The
existing PISCES installation is not migrated by cloning this repository.

[Get started](docs/quickstart.md) · [Understand the court](docs/how-it-works.md) ·
[Pass the crown](docs/succession.md) · [Read the limits](docs/limits.md)
