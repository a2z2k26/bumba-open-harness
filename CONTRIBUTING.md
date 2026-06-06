# Contributing

This project is a local agent harness with security-sensitive runtime surfaces.
Small, well-tested changes are preferred.

## Local Setup

```bash
make setup
make test
```

## Pull Request Checklist

- Keep Python source under `agent/`.
- Add or update tests for behavior changes.
- Run `make test` for offline checks.
- Run `make lint` when touching Python.
- Run `make secrets-scan` before publishing.
- Do not include personal operator data, local paths, runtime state, or secrets.

## Public Data Boundary

Examples should use placeholders such as `<openrouter-api-key>`,
`<claude-oauth-token>`, `portfolio.example.com`, and
`https://www.linkedin.com/in/example-operator`. Do not use a real person,
database, company-internal URL, or machine-specific path in committed examples.

## Live Integrations

Live tests and live service runs are opt-in. Do not run them in shared CI unless
the relevant credentials, cost caps, provider terms, and approval boundaries are
explicitly configured.
