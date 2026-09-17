# Flow Bridge Roadmap

Evidence gates, not calendar dates.

## M0 — Runtime portability — PASS

- configurable Chromium-family executable;
- real executable version detection;
- profile/runtime major-version guard;
- no-spend Flow bootstrap canary;
- no dependence on Playwright's fixed `chrome` channel.

## M1 — Durable control plane — PASS

- SQLite job store;
- unique request IDs;
- explicit state machine;
- append-only event journal;
- `UNKNOWN_STATE` fail-closed terminal state;
- job inspection CLI.

Invariant: ambiguous submission never causes an automatic resubmit.

## M2 — Multi-account foundation — PASS / LIVE EVIDENCE PARTIAL

Implemented:

- privacy-safe profile inventory;
- runtime compatibility health;
- per-account enable/disable policy;
- per-account max concurrency and scheduling priority;
- explicit health state (`UNKNOWN`, `HEALTHY`, `AUTH_REQUIRED`, `UNHEALTHY`);
- automatic scheduling only after a passing account canary;
- deterministic load-aware scheduler across healthy profiles;
- durable account/job association.

Remaining evidence gate: authenticate at least two independent Flow profiles and prove session isolation and scheduling across both.

## M3 — Exactly-once generation vertical slice — PASS

Live-validated path:

```text
spec
-> stable request_id
-> account assignment
-> existing Flow project
-> Veo 3.1 Lite selection
-> submit checkpoint
-> remote media/workflow checkpoint
-> terminal result
-> download
-> MP4 validation
-> COMPLETED
```

Validated properties:

- one output per request;
- no automatic retry;
- explicit model and aspect selection;
- remote handle captured before long polling completes;
- replaying the same request ID returns the existing artifact without opening Flow again.

## M4 — Recovery + observability — PARTIAL

PASS:

- classified failure states;
- durable transition/event evidence;
- metrics by state/kind/account;
- unresolved-job inventory;
- pre-submit failure reconciliation evidence;
- no-spend canaries.

OPEN:

- post-restart reconciliation of an already-submitted generation on migrated `flow.google.com` accounts.

Observed blocker: reopening a project did not replay historical status/result traffic, and the legacy direct status poll path may fail authentication on migrated accounts. Until a no-submit recovery path is demonstrated, ambiguous jobs stay `UNKNOWN_STATE` and cannot retry automatically.

## M5 — MCP semantic surface — PASS

Implemented and live-canary validated on MCP SDK 2.x:

- account status;
- privacy-safe doctor;
- durable no-spend canary;
- metrics;
- job list;
- unresolved-job list;
- job status;
- exactly-once Veo Lite generation.

Generation is annotated non-read-only and idempotent. The canary is also non-read-only because it records local durable state, although it does not spend generation credits. Inspection tools are read-only.

Generic click/type/browser-control primitives are intentionally out of scope.

## M6 — Multi-account production evidence — OPEN

With 2+ authenticated accounts:

- prove isolated profile directories;
- verify independent session health;
- add project/account affinity where needed;
- enforce max concurrency per account;
- prove scheduler avoidance of unhealthy/incompatible profiles;
- prove restart preserves account/job association.

## M7 — OSS hardening — IN PROGRESS

- CI for supported Python versions;
- security and contribution documentation;
- source/privacy sweep;
- clean wheel/sdist build;
- public repository;
- issue templates and release policy;
- evaluate upstream contribution for custom Chromium executable support.

## Provider migration rule

Everything above the provider/browser adapter must survive a future official Google Flow API. Browser-specific code remains isolated so jobs, scheduler, CLI/MCP contracts and observability do not need to change when the provider changes.
