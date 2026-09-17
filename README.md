# Flow Bridge

Flow Bridge is an experimental, open-source control plane for Google Flow.

It builds on [`gflow-cli`](https://github.com/ffroliva/gflow-cli) and adds the operational layer needed by agents and long-running automation: portable browser runtimes, durable exactly-once jobs, account scheduling, observability, canaries, and semantic CLI/MCP interfaces.

> **Unofficial. Not affiliated with Google.** Google Flow is a web product whose UI and private transport can change without notice. Browser-driven automation can break even when this project has not changed.

## Why Flow Bridge

`gflow-cli` already solves the hard provider problem: driving Google Flow through an authenticated browser session. Flow Bridge deliberately does not fork that work. It focuses on orchestration around it:

- use the Chromium-family browser that actually owns the local profile instead of assuming Playwright's fixed `chrome` channel;
- choose among isolated local profiles;
- persist every job and state transition in SQLite;
- prevent duplicate paid submissions with stable request IDs;
- fail closed when submission state is ambiguous;
- expose agent-friendly semantic operations through `flowctl` and MCP;
- keep the browser-specific adapter replaceable by a future official Google Flow API.

## Current status

The current development build has been live-validated on Windows against a migrated `flow.google.com` account.

### Working end to end

- configurable Chromium-family browser runtime;
- profile/runtime major-version safety guard;
- privacy-safe account inventory;
- deterministic multi-account scheduler with enable/disable, per-account concurrency limits, priorities, and health-canary gating;
- SQLite job store and event journal;
- durable no-spend Flow canary;
- exactly-once text-to-video submission using Veo 3.1 Lite;
- migrated-host project targeting;
- media/workflow checkpoint capture;
- download and MP4 validation;
- idempotent replay that returns the existing artifact without reopening Flow;
- metrics and unresolved-job inspection;
- semantic MCP server using MCP SDK 2.x;
- Linux/VPS invisible-browser runtime support (Xvfb virtual display, with optional true headless mode);
- Streamable HTTP MCP daemon mode for systemd-managed deployments.

A live vertical slice produced and validated an 8-second H.264/AAC portrait MP4 through the normal Google Flow UI path. Account IDs, project IDs, media IDs, prompts, and local profile paths are intentionally not part of this repository.

### Known limitations

- **Multi-account:** scheduler and isolation logic exist, but live validation currently covers one authenticated account. Two-account scheduling remains an evidence gate.
- **Post-restart recovery on migrated Flow:** gflow can capture `media_id` / `workflow_id` during a live run, but `flow.google.com` does not re-emit completed-job status traffic merely by reopening a project, while gflow's legacy direct status poller uses an endpoint that migrated accounts may reject. Ambiguous post-submit jobs therefore remain fail-closed instead of being automatically resubmitted.
- **Generation scope:** v0 allows one Veo Lite output per request. This is intentionally narrow while spend/recovery behavior is hardened.
- **Existing project required:** migrated `flow.google.com` generation currently needs an existing Flow project ID.

## Install for development

Requires Python 3.11+ and an authenticated `gflow-cli` profile.

```bash
uv sync --extra dev
```

Run the deterministic gate:

```bash
uv run ruff check src tests
uv run pyright src
uv run pytest -q
uv build
```

## CLI

Inspect local profiles without exposing Google account emails:

```bash
uv run flowctl accounts list
```

Configure scheduling policy for one authenticated profile:

```bash
uv run flowctl accounts configure <profile> \
  --max-concurrency 1 \
  --priority 100

uv run flowctl accounts disable <profile>
uv run flowctl accounts enable <profile>
```

Each gflow profile is treated as an isolated Google account. Automatic scheduling only uses accounts that are enabled, browser-compatible, below their concurrency limit, and have passed a Flow Bridge canary. Account emails and browser credentials are never stored in the scheduler database.

Run a zero-generation Flow bootstrap canary:

```bash
uv run flowctl canary --profile <profile>
```

Inspect operational state:

```bash
uv run flowctl metrics
uv run flowctl jobs list
uv run flowctl jobs unresolved
uv run flowctl jobs inspect <job-id>
```

Generate exactly one Veo Lite video:

```bash
uv run flowctl generate video \
  "A simple test scene" \
  --profile <profile> \
  --project-id <flow-project-uuid> \
  --request-id <stable-id>
```

`request-id` is the exactly-once boundary. Reusing the same ID returns the existing job rather than submitting another paid generation.

## MCP

Start the stdio MCP server:

```bash
uv run flowctl-mcp
```

Or run it as a loopback-only Streamable HTTP daemon:

```bash
DISPLAY=:98 FLOW_BRIDGE_HEADLESS=0 uv run flowctl-mcp \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8877 \
  --path /mcp
```

Current semantic tools include account health, metrics, job status, and exactly-once video generation. Credit-spending tools are marked non-read-only and idempotent in their MCP annotations.

Flow Bridge intentionally does **not** expose generic `click`, `type`, or arbitrary browser-control tools.

## Browser runtime

Set an explicit Chromium-family executable when auto-detection is not appropriate:

```bash
FLOW_BRIDGE_BROWSER_EXECUTABLE=/path/to/browser flowctl doctor --profile <profile>
```

On Windows, Flow Bridge can use installed Brave, Google Chrome, or Edge. On Linux it can also discover Chromium installed in Playwright's user cache. It reads the executable's real version and refuses to open a profile with an older Chromium major than the one that last wrote it.

Normal VPS operation should run headed Chromium on a private Xvfb display (`DISPLAY=:98`, `FLOW_BRIDGE_HEADLESS=0`). The browser is invisible to the operator and no VNC is needed during generation. A temporary VNC surface is only needed for initial login/MFA or exceptional reauthentication. True Playwright headless remains available for explicit testing. See [`docs/VPS.md`](docs/VPS.md).

## Security model

Treat browser profiles as credentials. They contain active authenticated sessions.

Never commit or share:

- browser profile directories;
- cookies, tokens, storage-state files, or MFA material;
- raw HAR captures;
- signed Google media URLs;
- account-specific incident bundles;
- private prompts or generated artifacts unless intentionally published.

Login/MFA remains user-driven in a visible browser. Flow Bridge does not store Google passwords, bypass CAPTCHA, export session cookies as an API credential, or spoof browser fingerprints.

See [`SECURITY.md`](SECURITY.md) for the full policy.

## Architecture

```text
Agent / automation
       |
  CLI / MCP
       |
Flow control plane
 jobs | scheduler | metrics
       |
 gflow adapter
       |
configurable Chromium runtime
       |
   Google Flow
```

Everything above the gflow/browser adapter is intended to survive a future official Google Flow API.

## License

MIT. See [`LICENSE`](LICENSE).
