# Configuration and troubleshooting

All configuration is local to the machine. Default config path: `~/.ai-cli-pool/config.json` on Linux, `%USERPROFILE%\.ai-cli-pool\config.json` on Windows. Override for tests or nonstandard use with `AIFULL_CONFIG` and `AIFULL_STATE_DIR`.

`aifull init --yolo` builds a provider-independent schema with two `providers` entries (`claude` and `codex`), three profile paths each, and dashboard account IDs. The config can be changed by hand after setup. Keep it private; it does not contain tokens but it identifies local account structure.

## Reuse existing dashboard accounts

For a dashboard project containing:

```
~/Desktop/SerenaProjects/codex-dashboard/runtime/claude/claude1
~/Desktop/SerenaProjects/codex-dashboard/runtime/claude/claude2
~/Desktop/SerenaProjects/codex-dashboard/runtime/claude/claude3
~/Desktop/SerenaProjects/codex-dashboard/runtime/accounts/account1
~/Desktop/SerenaProjects/codex-dashboard/runtime/accounts/account2
~/Desktop/SerenaProjects/codex-dashboard/runtime/accounts/account3
```

Run `./setup.sh --claude-root .../runtime/claude --codex-root .../runtime/accounts`. Note that the dashboard can also be configured with custom account directories or names. Inspect its actual settings first; matching the display name is insufficient when it maps to a different real account.

## Dashboard selection

Requests `GET https://token.openjvspace.com/api/accounts` without authentication headers and without `refresh=now`. The API must be reachable from the local machine and allow your client. No API contract beyond `accounts[]` and optional `recommended` is assumed. `status = ready`, a fresh result, and `headroom > min_headroom_percent` are required for automatic selection. If the backend changes, adjust your local `dashboard_account` mapping or update the adapter.

## Profiles and auth

- `aifull login claude 1` runs official `claude auth login` with `CLAUDE_CONFIG_DIR=<slot1>`.
- `aifull login codex 1` runs official `codex login` with `CODEX_HOME=<slot1>`.
- Reauthorize expired individual account with `aifull login PROVIDER SLOT`.
- Run `aifull auth PROVIDER all` and inspect output; use a private browser window for each browser OAuth flow if switching identities confuses the browser.
- The launcher removes API-key override variables from the child process to favor per-account sign-in. If you intentionally use API-key or enterprise auth, customize `AUTH_OVERRIDES` and verify CLI behavior separately.

## Resuming Codex

The launcher finds interactive Codex session metadata (`sessions/.../rollout-*.jsonl`) and resumes by ID only within the same `CODEX_HOME`. It does not read transcript message content. If a future Codex version changes its local storage scheme, starting a fresh session still works; use `codex resume` directly as an interim fallback and update the adapter. Never copy an entire `CODEX_HOME` directory between accounts because it can mix authentication material.

## Debug checklist

1. `claude --version` and `codex --version` must both resolve in the same shell.
2. `aifull doctor` prints the six profile directories.
3. `aifull auth claude all`, `aifull auth codex all` validate sign-in.
4. `aifull status` reports cached quotas and dashboard account IDs.
5. `aifull mode safe` disables the dangerous bypass flags while troubleshooting.
6. On Windows, after `setup.ps1`, reopen PowerShell so the user PATH is reloaded. From another terminal test `aifull help`.
7. If you share a dashboard's credential folders with the launcher, keep them on the same filesystem and protect them from simultaneous independent token refresh processes.
