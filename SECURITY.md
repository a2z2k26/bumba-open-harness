# Security Policy

## Supported Versions

This public repository is pre-1.0. Security fixes apply to `main` unless a
release branch is created later.

## Reporting

Do not open a public issue with live credentials, tokens, private logs, or
operator data. Report suspected exposure privately through the repository
owner's preferred GitHub security channel.

Include:

- A concise description of the issue.
- The affected file, command, or runtime surface.
- Whether any secret, token, local path, or personal data is involved.
- Reproduction steps that do not disclose the secret itself.

## Secret Handling

The harness must never commit:

- `.secrets`
- `.mcp.json`
- OAuth caches
- API keys or provider tokens
- Browser profiles and cookies
- SQLite databases, WAL files, and runtime logs
- Filled `candidate.json` or other personal job-search material

Run:

```bash
make secrets-scan
```

If a real credential is ever committed or printed in a public place, revoke it
at the provider and replace it. Removing it from the current tree is not enough.
