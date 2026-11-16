<p align="center">
  <img src="assets/keep-calm-and-dm-the-queen-square.png" width="400" alt="A red poster with a white crown and the words Keep Calm and DM the Queen.">
</p>

Managing dozens of coding agents can be a royal pain. But it doesn't have to be. Monarchy streamlines agent orchestration by letting you command agent empires through a single chat. Just talk to the Queen, and let Monarchy handle the rest. Her royal court delegates tasks to workers and supervises them through planning, implementation and review. Results and decisions that need your input come back to the
throne for your sign-off. Simplicity and centralization of power keeps order in the kingdom. Once the Crown is at your service, you'll never look back.

## Talk to the Queen

Tell the Queen what you want done, ask about work in flight, or change direction on something you kicked off hours ago. Nothing is off limits. Queen's got you. Her
Secretary keeps the workers moving and takes care of the follow-ups.

- **Ask in one chat.** New requests and follow-ups all go to the Queen. She
  keeps track of what you've asked for as the work moves between agents.
- **Leave the legwork to the royal court.** The Secretary assigns tasks, follows up
  when workers get stuck, and gets their work reviewed. The court passes along
  the context each agent needs.
- **Make the decisions that matter.** When a decision needs your judgment or
  permission, the Queen explains the tradeoffs and recommends a way forward.
  Give her your answer, and she takes it back to the workers.
- **See what's getting done.** The Queen tells you what finished, what was checked,
  and what's still open, with links when you want a closer look.

You can still peek into the other sessions whenever you like.
[How the conversation works →](docs/how-it-works.md)

## Meet the Royal Court

| Role | What they do |
| --- | --- |
| Queen | Takes your requests, keeps the goal in view, and brings back results and decisions. |
| Secretary | Assigns tasks, checks progress, arranges reviews, and manages handoffs. |
| Workers | Write code, investigate problems, and review changes, each with an assignment and a separate workspace. |

Even a monarchy has ground rules. The court handles routine questions within
your instructions. Changes to scope, spending, or actions you've reserved for
yourself come back to you. Each project keeps its own review and delivery rules.

## Why we built it

On PISCES, every new agent meant another conversation to keep up with. A fix
needed review, a reviewer needed context, and someone was waiting on an answer
buried in another tab. We kept carrying messages between agents.

So we gave that job to the court. Tell the Queen what you want, follow one
conversation, and let the agents sort out who does what.
[First Mate](https://github.com/kunchenguid/firstmate) helped shape the idea:
one agent to talk to, a team working behind the scenes, and important decisions
brought back to you.

## When the crown changes hands

_"The Queen is dead, long live the Queen!"_

Even Queens run out of context. Before handing over, an agent writes down
where things stand, including unfinished work and anything still running.
Its successor checks the handoff before taking over. Your decisions carry
over too.
[How succession works →](docs/succession.md)

## Start a court

Follow [the quickstart](docs/quickstart.md) to set up your Queen and give her
one task. Let the court do the coordination, then check the result in your
conversation with her.

The court has [twelve core skills](docs/skills.md) for taking requests, dividing
work, handling decisions, and passing the crown. Workers carry the skills and
project instructions they need in a checked package.

The [opt-in runtime](docs/runtime.md) keeps assignments, reports, decisions, and
delivery receipts in one private journal. The Secretary takes a bounded pass
through incoming reports; the Queen reads the decisions and checked results in
her inbox. Explicit delivery commands send work to Conductor sessions. Nothing
starts when you clone the repo, and no background service keeps the court running.

A separate [watcher](docs/observer.md) reads session and pull request status.
The bundled First Mate source is a pinned reference and compatibility fixture;
Monarchy's runtime uses Python and SQLite. Offline tests and live Conductor
verification cover different things. [Read the current limits](docs/limits.md).

You can use Monarchy's instructions with any project. **Conductor cloud is the
first runtime integration**; other runtimes need their own integration and
verification. Cloning this repository doesn't migrate the existing PISCES setup.

[Get started](docs/quickstart.md) · [Meet the Royal Court](docs/how-it-works.md) ·
[Pass the crown](docs/succession.md) · [Read the limits](docs/limits.md)
