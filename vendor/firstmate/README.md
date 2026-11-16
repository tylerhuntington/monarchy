# First Mate Source

`source.tar.gz` is the unmodified `git archive` of the revision and SHA-256 in
`manifest.json`. `LICENSE` preserves the upstream MIT notice. No upstream hook,
installer, daemon, or agent is run by cloning Monarchy.

Verify the archive:

```bash
python3 bin/firstmate.py verify
```

Extract it into a new private directory for compatibility work:

```bash
python3 bin/firstmate.py extract .monarchy/firstmate-source
```

The extractor validates all archive paths and internal symlinks before writing.
It refuses an existing destination. The offline tests exercise the upstream
`fm-branch-outcome.sh` command with an isolated operational home; Bash and jq are
required for that compatibility test. This proves that specific store behavior,
not native Conductor support or an unattended court.

Updates require a new pinned revision and digest, review of upstream changes,
and fresh compatibility tests. Keep internal upstream names intact and record
patches explicitly. The current snapshot has no Monarchy patches.

The court runtime does not import or launch this snapshot. Its only executable
use in this release is the explicit outcome compatibility test. Monarchy owns
its Python/SQLite runtime; upstream changes require a deliberate new pin and
compatibility run.
