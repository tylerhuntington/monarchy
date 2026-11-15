# Contributing

Keep Monarchy small enough to understand before running it. Explain the problem
and the resulting behavior in a PR. Include the checks you ran and any runtime
behavior you couldn't verify.

From the repository root, run the offline suite and whitespace check:

```bash
python3 -m unittest discover -s tests -v
git diff --check
```

The observer uses Python's standard library. Its tests must not launch agents,
contact people, mutate GitHub, or require credentials.

New runtime integrations need explicit identity validation, bounded reads,
uncertain-result recovery, and documented limits. A happy-path demo is not proof
of exclusive ownership, authenticated approval, or unattended recovery.

Keep the prose direct. Use the royal vocabulary when it explains a responsibility;
use ordinary engineering words for the work. Update the docs when behavior changes.
