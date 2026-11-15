<p align="center">
  <img src="assets/keep-calm-and-dm-the-queen-square.png" width="400" alt="A red poster with a white crown and the words Keep Calm and DM the Queen.">
</p>

*“The Queen is dead, long live the Queen.”*

Coding agents run out of context, and that can happen halfway through a task.
When a new session takes over, it needs to know where things left off and what
you've already decided. Monarchy makes that handoff part of the job, including
when the Queen herself needs a new session.

The Queen is your point of contact through all of this. You tell her what you
want to get done, and she works with the rest of the court to assign the work
and follow it through review. The agents coordinate with each other in the
background, while you stay in one conversation. When they need a decision from
you, the Queen brings it back with the context you need and a recommendation.

## Stay in one conversation

Give the Queen the goal. Follow one conversation. Let the court handle the rest.

- **Ask in one place.** Bring requests, changes of direction, and status questions
  to the Queen's thread.
- **Let the agents coordinate.** The court assigns work, follows up on blockers,
  arranges reviews, and passes context between sessions.
- **Decide what matters.** When work needs your judgment or permission, the Queen
  brings the choice, the tradeoff, and a recommendation. She carries your answer
  back to the agents.
- **Get a clear result.** The Queen explains what finished, what was verified,
  and what still needs attention, with links when you want the detail.

You can inspect the other sessions. Keeping up with every tab isn't meant to be
your job. [How the conversation works →](docs/how-it-works.md)

## Behind the scenes

| Role | What they do |
| --- | --- |
| Queen | Your point of contact for goals, decisions, status, and results. |
| Chamberlain | Coordinates assignments, progress, reviews, and handoffs. |
| Workers | Build, investigate, and review bounded tasks in their own workspaces. |

The Queen keeps the overall request in view while the court handles the steps.
Routine questions stay with the agents when they can resolve them within your
instructions. Changes to scope, spending, or actions you've reserved come back
to you. Each project keeps its own review and delivery rules.

## Why we built it

Working with several agents meant following several conversations. A fix needed
review, a reviewer needed context, and a blocked agent needed an answer from
another tab. Too much of the coordination came back to the person who asked for
the work.

Monarchy grew out of that experience on PISCES. We wanted one place to explain
the goal and follow the outcome, with the agents doing the coordination.
[First Mate](https://github.com/kunchenguid/firstmate) helped shape that approach:
a single point of contact, delegated work, and important decisions brought back
to the user. Monarchy gives that relationship a royal vocabulary.

## When a session ends

The crown belongs to the role, not the chat window. A replacement Queen should
pick up your requests, decisions, and unfinished work from the court's records.
Careful handoffs support the promise of one point of contact, even when the
underlying session changes. [How succession works →](docs/succession.md)

## Start a court

Follow [the quickstart](docs/quickstart.md) to set up the Queen and try one task.
The first checkpoint is a result returned to her thread without you carrying
messages between agents.

This first version contains agent instructions, reusable briefs and handoffs,
a Conductor guide, and a Python status watcher. The workflow is supervised:
agents use the host's tools, and the watcher reads session and PR state. It does
not launch agents, transfer authority, or keep itself running after its host exits.

The instructions are project-independent. **Conductor cloud is the first runtime
integration**; other runtimes need their own integration and verification. The
existing PISCES installation is not migrated by cloning this repository.

[Get started](docs/quickstart.md) · [Meet the court](docs/how-it-works.md) ·
[Pass the crown](docs/succession.md) · [Read the limits](docs/limits.md)
