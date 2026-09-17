# Flow Bridge agent rules

Read `PROJECT_CONTEXT.md` and `README.md` before non-trivial work.

## Scope

This repository is the open-source operational/control-plane layer around Google Flow. Do not copy private paths, secrets, account data, product-specific business logic, or private infrastructure into public code.

## Upstream discipline

`gflow-cli` is the browser/provider foundation. Before adding a capability, check whether upstream already provides it. Prefer:

1. adopt as-is;
2. contribute upstream when the capability belongs in gflow itself;
3. implement here only when it is a Flow Bridge operational concern.

Do not fork browser automation logic merely to own it locally.

## Safety

- Browser profiles are secrets.
- Never print cookies, tokens, passwords, MFA, account emails, raw HAR contents, or signed URLs.
- Login remains interactive and user-driven.
- No CAPTCHA bypass or stealth/fingerprint spoofing beyond ordinary browser configuration required to avoid false automation flags.
- No generation in tests unless the run explicitly opts into a credit-spending E2E marker and budget.
- Unknown submission state must not auto-resubmit.

## Validation

For every behavior change:

- unit tests for deterministic logic;
- a no-spend local canary when browser/runtime behavior changes;
- exact evidence for the affected profile/browser/runtime combination;
- preserve CLI/MCP parity once MCP commands exist.

A passing build alone is not proof for browser, auth, or Flow integration changes.

## Architecture constraints

Keep these boundaries explicit:

- control plane / jobs / scheduler / observability;
- provider abstraction;
- gflow adapter;
- browser runtime selection;
- CLI/MCP adapters.

The browser-specific adapter must remain replaceable by a future official Google Flow provider.
