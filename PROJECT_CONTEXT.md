# Flow Bridge — Project Context

## Purpose

Flow Bridge is an open-source, agent-friendly control plane for Google Flow. It is intentionally layered on top of `gflow-cli` rather than reimplementing Google Flow browser automation.

Primary goals:

- reliable browser/runtime selection across Chromium-family browsers;
- first-class isolated account profiles and scheduling;
- durable, idempotent jobs;
- observable spend boundaries and event history;
- semantic CLI and MCP interfaces;
- no-spend canaries;
- a replaceable provider boundary so a future official Google Flow API can replace browser automation.

## Product boundary

Flow Bridge owns orchestration: jobs, idempotency, account selection, health, observability and agent-facing contracts.

`gflow-cli` owns Google Flow provider behavior and UI/wire adaptation. Upstream capabilities should be adopted or contributed upstream rather than copied here.

## Evidence state

Validated locally on Windows against the migrated `flow.google.com` frontend:

- configurable real Chromium-family executable;
- authenticated persistent browser profile reused successfully;
- runtime/profile Chromium-version compatibility checked before launch;
- no-spend bootstrap canary completes through gflow's UI automation transport;
- one exactly-once Veo 3.1 Lite T2V generation completed, downloaded and passed MP4 validation;
- replay of the same request ID returned the existing artifact without reopening Flow;
- durable job/event state survived separate CLI invocations;
- MCP SDK 2.x semantic tool schemas validated.

Evidence intentionally excludes account identifiers, Flow project/media UUIDs, private prompts and local user paths from source control.

## Known gap: migrated-host recovery

Flow Bridge records `media_id` and `workflow_id` as soon as gflow observes a successful remote submit. This is enough to prevent blind retries, but not yet enough to guarantee post-process-restart recovery on migrated accounts.

Observed behavior:

- reopening a completed Flow project did not cause the SPA to re-emit status/result RPCs for that existing generation;
- gflow's legacy direct video-status poll path can be rejected by migrated accounts.

Until a no-submit reconciliation path is demonstrated, a job whose remote state is ambiguous remains terminal `UNKNOWN_STATE`. Automatic resubmission is forbidden.

## Architecture

```text
Agent / automation
       |
  CLI / MCP
       |
Flow control plane
       |
provider adapter (gflow today)
       |
configurable Chromium runtime
       |
   Google Flow
```

## Security invariants

- Never commit browser profiles, cookies, tokens, HARs, secrets, Google account identifiers, raw signed media URLs, private prompts, or account-specific incident bundles.
- User login/MFA remains user-driven in a visible browser.
- No credential extraction, CAPTCHA bypass, proxy/fingerprint spoofing, or session export as a pseudo-API credential.
- Paid generation is idempotent by request ID and currently constrained to one output per request.
- Unknown post-submit state fails closed rather than resubmitting.

## Development rule

Before adding a capability, determine whether it belongs upstream in `gflow-cli` or in this operational layer. Prefer the smallest implementation that preserves provider replaceability and can be validated without spending credits whenever possible.
