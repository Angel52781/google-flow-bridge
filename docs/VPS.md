# VPS deployment

Flow Bridge is designed to run without a visible browser during normal operation. A Chromium-family process still exists underneath the provider. On Linux VPS deployments the recommended mode is currently **headed Chromium on an Xvfb virtual display**: no physical window or VNC is required, while the browser remains in the mode Google Flow/gflow validates most reliably. True Playwright headless remains available as an explicit option, not the production default.

## Runtime layout

Recommended separation:

```text
source checkout          read-only application code
FLOW_BRIDGE_HOME         SQLite jobs + downloaded artifacts
GFLOW_CLI_HOME           authenticated browser profiles
browser cache/binary     Chromium runtime
systemd --user           MCP daemon lifecycle
```

Browser profiles are credentials. Keep `GFLOW_CLI_HOME` outside the source checkout and mode-restrict it to the operator.

## Bootstrap

1. Install/sync the project with `uv sync --extra dev`.
2. Install Chromium through Playwright/gflow or point `FLOW_BRIDGE_BROWSER_EXECUTABLE` at an existing compatible Chromium-family binary.
3. Create private state directories for `FLOW_BRIDGE_HOME` and `GFLOW_CLI_HOME`.
4. Authenticate each Flow account once in a visible Chromium session on the **same VPS profile** that headless operation will later reuse.
5. Shut down the temporary VNC/tunnel surface. Keep only the private Xvfb display used by the daemon.
6. Run a zero-generation canary on the virtual display:

```bash
DISPLAY=:98 FLOW_BRIDGE_HEADLESS=0 flowctl doctor --profile <profile>
DISPLAY=:98 FLOW_BRIDGE_HEADLESS=0 flowctl canary --profile <profile>
```

7. Install the Xvfb and MCP systemd user units and start the daemon.

## Authentication

Do not copy browser cookies, passwords, MFA material, or exported storage-state between hosts.

A profile captured on Windows should not be assumed portable to Linux. The safe bootstrap is a one-time visible login on the Linux VPS itself. A temporary VNC/noVNC session is appropriate for this, provided:

- VNC listens only on loopback;
- the external tunnel is short-lived;
- the VNC session has a strong temporary password;
- the tunnel and graphical processes are stopped immediately after authentication;
- no browser DevTools port is exposed publicly.

Normal generation must not require VNC or a physical display.

## Virtual headed mode, headless, and sandboxing

Flow Bridge defaults to headed operation. On a VPS, pair that with Xvfb (`DISPLAY=:98`) so Chromium remains invisible to the operator. Set `FLOW_BRIDGE_HEADLESS=1` only when intentionally testing true Playwright headless mode; it is not the recommended production default while upstream Flow automation documents stronger bot-detection risk there.

Some VPS kernels prevent Chromium's native sandbox from starting. Flow Bridge does **not** silently disable it. If the host has additional isolation and the operator accepts the tradeoff, set:

```bash
FLOW_BRIDGE_BROWSER_NO_SANDBOX=1
```

This appends Chromium's `--no-sandbox` flag explicitly. Prefer a dedicated OS account, systemd hardening, container/user-namespace isolation, or another browser sandbox whenever available.

## MCP daemon

`flowctl-mcp` supports stdio and Streamable HTTP:

```bash
flowctl-mcp --transport streamable-http --host 127.0.0.1 --port 8765 --path /mcp
```

Bind to loopback by default. Do not expose the MCP endpoint directly to the public internet. Put authenticated infrastructure such as an existing internal relay in front of it when remote access is required.

## systemd

Start from both `deploy/systemd/flow-bridge-xvfb.service.template` and `deploy/systemd/flow-bridge-mcp.service.template`. Replace:

- `@FLOW_BRIDGE_ROOT@`
- `@FLOW_BRIDGE_STATE@`
- `@GFLOW_CLI_HOME@`

with operator-local paths, write the unit under `~/.config/systemd/user/`, and keep the environment file at `~/.config/flow-bridge/flow-bridge.env` with mode `0600`.

Then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now flow-bridge-xvfb.service
systemctl --user enable --now flow-bridge-mcp.service
systemctl --user status flow-bridge-mcp.service
```

## Acceptance gate

A VPS deployment is not considered proven until all of these pass from the Linux host:

1. deterministic lint/type/test/build gate;
2. browser/profile compatibility check;
3. invisible virtual-display `doctor`;
4. invisible zero-generation canary;
5. daemon restart followed by another canary;
6. one explicitly authorized Veo Lite generation;
7. artifact validation;
8. same-`request_id` replay returns the existing job without another submit.

Post-submit recovery after process loss remains a separate evidence gate on migrated `flow.google.com` accounts. Until it is solved, ambiguous jobs remain fail-closed.
