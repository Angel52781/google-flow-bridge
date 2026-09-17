# Contributing to Flow Bridge

Flow Bridge is experimental and sits in front of a browser session that can spend Google Flow credits. Changes should therefore optimize for evidence, fail-closed behavior and small provider-specific surfaces.

## Development setup

```bash
uv sync --extra dev
```

Run the local deterministic gate before proposing a change:

```bash
uv run ruff check src tests
uv run pyright src
uv run pytest -q
uv build
```

## Before implementing

1. Check whether the capability already exists in `gflow-cli`.
2. If it is Google Flow provider/UI behavior, prefer an upstream contribution.
3. Add code here when the concern is operational: jobs, scheduling, idempotency, observability, provider abstraction, CLI or MCP control-plane behavior.

## Tests

- Pure state/scheduling/idempotency behavior must have unit tests.
- Browser/runtime changes should have a no-spend canary where possible.
- Credit-spending E2E work must be explicitly opted into and bounded to a known number of submissions.
- A test must never retry a paid generation after an ambiguous submit.

## Security and privacy

Use synthetic profile names, project IDs, prompts and paths in tests/docs. Never commit browser profiles, cookies, Google account identifiers, signed URLs, private prompts, raw HARs, raw incident bundles or generated customer assets.

Review `SECURITY.md` before changing authentication, browser-profile handling, job recovery or MCP generation tools.

## CLI / MCP

Expose semantic operations such as `generate video`, `job status` or `accounts status`. Do not add generic browser primitives such as arbitrary click/type/evaluate tools.

When a capability is available in both surfaces, preserve the same safety semantics and payload meaning. Paid MCP tools must be clearly annotated as non-read-only; idempotent operations should advertise that property.

## Pull requests

A useful pull request states:

- the capability or defect;
- whether the change belongs here or upstream and why;
- tests run and exact results;
- any live Flow evidence used;
- whether credits were spent;
- unresolved limitations or provider assumptions.

Do not claim live verification when only unit tests ran.
