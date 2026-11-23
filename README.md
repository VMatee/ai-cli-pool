# AI CLI Pool

**One local command to manage 3 Claude Code + 3 OpenAI Codex CLI accounts.** Runs in native Windows PowerShell and Ubuntu Bash, with cached quota selection from [token.openjvspace.com](https://token.openjvspace.com/).

> [!WARNING]
> This project's installer defaults to **YOLO mode**, at the owner's request. This bypasses approval prompts and, for Codex, sandbox restrictions. Run only on trusted or isolated development machines, commit/backup changes regularly, and never point an untrusted prompt at valuable data. Disable instantly with `aifull mode safe`.

## What works

| Feature | Claude Code | Codex CLI |
|---|---|---|
| Three independently stored logins per machine | Yes (`CLAUDE_CONFIG_DIR`) | Yes (`CODEX_HOME`) |
| Native Windows / Ubuntu | Yes | Yes |
| YOLO launcher option | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` |
| Dashboard quota-based selection | Yes | Yes |
| Resume the last project session in **same** account | Yes | Yes |
| Change local accounts | Fork transcript to a new session | Start a new conversation + project handoff |
| Move projects across computers | Git + reviewed handoff summary | Git + reviewed handoff summary |

**Not supported:** live changes to a running CLI's authenticated identity, merging Claude/Codex history, automatically syncing raw session transcripts across PCs, automatic mid-response account rotation, bypassing provider-imposed account restrictions. Account switching happens between CLI launches.

## Requirements

- Python **3.9+**, Git recommended.
- Both [official Claude Code CLI](https://code.claude.com/docs/en/setup) and [official Codex CLI](https://github.com/openai/codex#installing-and-running-codex-cli) installed and usable as `claude` / `codex`.
- A Claude subscription/login and a Codex/ChatGPT login for each of your three slots (six sign-ins per computer when using all slots). Official interactive authentication only; **no credentials are added to this repository**.

### Install official CLIs

Ubuntu:

```bash
curl -fsSL https://claude.ai/install.sh | bash
npm install -g @openai/codex
```

Windows PowerShell:

```powershell
irm https://claude.ai/install.ps1 | iex
npm install -g @openai/codex
```

These are vendor-maintained installers. Review their instructions and trust policies before executing remote installation scripts. Another option for Codex when you already have Node/npm: `npm install -g @openai/codex`.

## Quick start: Ubuntu

```bash
git clone https://github.com/VMatee/ai-cli-pool.git
cd ai-cli-pool
./setup.sh --login-all
```

Login opens each official CLI in turn; select the corresponding browser account for slots 1, 2, 3. For an existing Linux usage dashboard, **reuse its existing profile folders** rather than creating duplicate logins:

```bash
./setup.sh \
  --claude-root "$HOME/Desktop/SerenaProjects/codex-dashboard/runtime/claude" \
  --codex-root "$HOME/Desktop/SerenaProjects/codex-dashboard/runtime/accounts"
# Add --login-all only when those slots have not yet been authenticated.
```

Open a new terminal so `~/.local/bin` is on your `PATH`. On a machine using Zsh, add `export PATH="$HOME/.local/bin:$PATH"` to `~/.zshrc`.

## Quick start: Windows 10/11 (native PowerShell)

```powershell
git clone https://github.com/VMatee/ai-cli-pool.git
cd ai-cli-pool
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -LoginAll
```

The PowerShell setup itself does **not** use AI YOLO privileges; the `-ExecutionPolicy Bypass` is for launching your locally cloned setup script. You may prefer `Set-ExecutionPolicy -Scope Process Bypass` or an organization-approved script signing workflow.

Open a **new** PowerShell terminal after installation. Setup writes launcher `.cmd` wrappers into `%USERPROFILE%\.ai-cli-pool\bin` and adds that directory to the user PATH. PowerShell runs `.cmd` wrappers by name.

To keep approval/sandbox controls instead of YOLO during setup:

```powershell
.\setup.ps1 -Safe
```

## Everyday commands (same on both OSes)

```text
claudefull                Select Claude account from dashboard, resume project
claudefull 1              Force Claude account 1
claudefull 2              Force Claude account 2
claudefull new            New Claude session
codexfull                 Select Codex account from dashboard, resume project
codexfull 3               Force Codex account 3
codexfull new             New Codex session

aifull claude             Same as claudefull
aifull codex              Same as codexfull
aifull status             Check both providers' cached quota
aifull status claude      Only Claude quotas
aifull status codex       Only Codex quotas
aifull doctor             Show local CLI/profile paths
aifull login-all          Interactive login of all six slots
aifull login claude 2     Reauthorize Claude account 2
aifull login codex 3      Reauthorize Codex account 3
aifull auth claude all    Show Claude login state
aifull auth codex all     Show Codex login state
aifull mode yolo          Enable BOTH providers' YOLO flags
aifull mode safe          Disable BOTH providers' YOLO flags
aifull handoff            Write a portable project handoff template
```

Forward your own CLI arguments after `--`:

```bash
claudefull 2 -- --model sonnet
codexfull 3 -- -m gpt-5.3-codex
```

Run `claudefull` / `codexfull` **from the project directory**, not from the launcher repository, to preserve per-project history.

## Credentials and quota mapping

All credentials are managed by the official provider CLI in isolated **local** folders. No login/logout for routine switching. The first login for each account on **each** computer is still required; Windows and Ubuntu are not automatically logged in to each other's sessions.

Default mapping:

| Provider | Launcher slot | `token.openjvspace.com` account ID | Local environment |
|---|---|---|---|
| Claude | 1, 2, 3 | `claude1`, `claude2`, `claude3` | `CLAUDE_CONFIG_DIR` |
| Codex | 1, 2, 3 | `account1`, `account2`, `account3` | `CODEX_HOME` |

**Important:** make sure that each local slot holds the **same real account** as the corresponding dashboard slot. Otherwise quota-based selection will be misleading. The dashboard API is a cached source of *usage numbers*, not a credential proxy. The launcher does not read OAuth tokens and does not call provider usage endpoints itself.

If your Codex dashboard uses different IDs, edit only the `dashboard_account` fields in `~/.ai-cli-pool/config.json` (Windows `%USERPROFILE%\.ai-cli-pool\config.json`). You can also change individual profile `path` fields to point at existing dashboard folders. `aifull init` will never overwrite your existing config.

A cached response should look like:

```json
{
  "recommended": {"claude": "claude:claude2", "codex": "codex:account1"},
  "accounts": [
    {"provider":"claude","account":"claude2","status":"ready","headroom":65},
    {"provider":"codex","account":"account1","status":"ready","headroom":80}
  ]
}
```

If the dashboard is unreachable, the launcher reuses the last local slot for that project/provider or defaults to slot 1. If all reported accounts are exhausted or stale, automatic selection stops instead of silently ignoring the quota status; a slot can still be selected manually. No forced refresh on every startup; the dashboard controls polling and backoff.

## Session continuity

- **Claude / same account:** resumes its last local project transcript.
- **Claude / another account:** resumes by absolute transcript path and creates a *forked* session ID. The original remains untouched.
- **Codex / same account:** resumes by its local session ID.
- **Codex / another account:** creates a *new conversation*, reading a handoff file when available. Cross-account Codex transcript reuse is not promised or emulated.
- **Claude <-> Codex or Windows <-> Ubuntu:** use the same source repository and a reviewed `.ai-cli-pool-handoff.md` committed in the *project repository*. Fill out the handoff before switching. The handoff is never generated automatically with invented progress.

From your project directory:

```bash
aifull handoff
# Edit the TODOs, review for sensitive data, then in your PROJECT repository:
git add .ai-cli-pool-handoff.md
git commit -m "Save portable AI task handoff"
git push
```

On the other PC, `git pull` and run `claudefull` or `codexfull`. This recovers task-level progress, **not** the exact original token-level conversation. `CLAUDE.md`, `AGENTS.md`, source code, commits and tests remain the primary shared project context.

## Security

- Repository may be **public**; **never** commit `.credentials.json`, `auth.json`, OAuth refresh tokens, account profile directories, `.env` files, or raw `.jsonl` transcripts.
- The source repository `.gitignore` excludes common secrets, but **other projects require their own `.gitignore`**.
- Credential folders do not automatically sync to GitHub; don't put them inside a Git working tree.
- Account and provider selection uses only the cached dashboard metadata. Your configured dashboard can be public; don't expose your local credentials or your dashboard's authentication headers.
- YOLO mode can execute destructive commands and access files outside the project. For safer work, `aifull mode safe`.
- Project-local lock prevents two *pool-managed* sessions from editing the exact same directory simultaneously. It does not prevent launching raw `claude` or `codex` elsewhere.

## Development / tests

```bash
python3 -m unittest discover -s tests -v
bash -n setup.sh
```

GitHub Actions runs isolated tests on Ubuntu and Windows with Python 3.9 and 3.13. Tests simulate provider CLIs and a local quota dashboard; CI does **not** authenticate or run paid inference. Run a first real interactive login and launch on each OS before depending on this for production work.

## References

- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Claude Code configuration](https://code.claude.com/docs/en/settings)
- [OpenAI Codex CLI source / installation](https://github.com/openai/codex)
- [Codex CLI options](https://github.com/openai/codex/blob/main/codex-rs/cli/src/main.rs)
