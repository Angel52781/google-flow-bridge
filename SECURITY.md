# Security Policy

Flow Bridge controls a local authenticated Google Flow browser session. Treat that session as a credential.

## Sensitive material

Never commit, upload to an issue, paste into chat, or include in logs intended for third parties:

- Chromium/Chrome/Brave profile directories;
- cookies, OAuth/session tokens, storage-state files, passwords, MFA or recovery codes;
- raw HAR files;
- signed media URLs;
- Google account identifiers unless intentionally disclosed by the owner;
- raw incident bundles without review and redaction;
- private prompts, generated media, or customer/project data.

The repository `.gitignore` blocks common profile, cookie, HAR, incident and artifact paths, but ignore rules are not a substitute for review.

## Authentication

Login and MFA are user-driven in a visible browser. Flow Bridge does not request or persist Google passwords or MFA secrets and does not export browser cookies as an application credential.

## Browser automation boundary

Flow Bridge uses ordinary user-authorized browser automation. It does not attempt to bypass CAPTCHA, defeat access controls, rotate proxies, forge browser fingerprints, or reverse-engineer authentication secrets.

## Paid operations

Video generation can consume Google Flow credits.

Current safeguards:

- stable request IDs are unique in the durable SQLite job store;
- replaying an existing request ID does not submit a second generation;
- v0 allows one Veo Lite output per request;
- the credit-spending submit boundary is checkpointed;
- remote media/workflow handles are recorded when observed;
- an ambiguous post-submit state becomes terminal `UNKNOWN_STATE`;
- `UNKNOWN_STATE` cannot automatically transition back to submit.

## Browser profile compatibility

Opening a Chromium profile with an older browser major can damage session state. Flow Bridge checks the profile's recorded Chromium version against the real executable version and refuses destructive downgrades when both versions are known.

## MCP

MCP inspection tools are marked read-only. Credit-spending generation is marked non-read-only and idempotent. Clients should still apply their own approval policy before invoking a paid tool.

## Reporting a security issue

Do not open a public issue containing credentials, session artifacts, signed URLs, private prompts or account data. Use GitHub's private vulnerability-reporting mechanism when enabled for the repository, or contact the maintainer privately.
