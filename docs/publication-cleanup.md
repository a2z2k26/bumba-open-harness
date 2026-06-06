# Publication Cleanup Notes

This repository was prepared as a no-history public tree.

## Removed From the Public Copy

- Private planning archives, handoffs, runtime evidence directories, and
  operator-only deployment notes.
- Local machine paths and workstation-specific runtime assumptions.
- Personal identity files and private operator profile material.
- Resume, portfolio, LinkedIn, and other private job-search context.
- Hardcoded Notion database IDs and job-search approval database references.
- Runtime secrets, OAuth tokens, API keys, browser profiles, SQLite databases,
  logs, and generated state.

## Public Defaults

- Voice is disabled by default.
- Job-search approval fails closed until a local database ID is configured.
- Browser profile paths use generic runtime locations.
- Claude and OpenRouter credentials are read from local secrets, not committed
  config.

## Verification Expectations

Before making the repo public or accepting external changes, run:

```bash
make test
make secrets-scan
```

For release-sensitive changes, also run targeted tests for the touched service
or backend.
