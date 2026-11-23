#!/usr/bin/env python3
"""AI CLI Pool: isolated multi-account Claude Code and Codex launcher (Python 3.9+).

This launcher never reads, writes, syncs or prints authentication tokens.
The official CLI owns credentials in CLAUDE_CONFIG_DIR or CODEX_HOME.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

APP_DIR = Path(os.getenv("AIFULL_HOME", str(Path.home() / ".ai-cli-pool"))).expanduser()
CONFIG_FILE = Path(os.getenv("AIFULL_CONFIG", str(APP_DIR / "config.json"))).expanduser()
STATE_DIR = Path(os.getenv("AIFULL_STATE_DIR", str(APP_DIR / "state"))).expanduser()
DASHBOARD_URL = "https://token.openjvspace.com/api/accounts"
PROVIDERS = ("claude", "codex")
SLOTS = ("1", "2", "3")
HANDOFF_FILE = ".ai-cli-pool-handoff.md"
AUTH_OVERRIDES = {
    "claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
               "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"),
    "codex": ("OPENAI_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL", "CODEX_API_KEY"),
}


def error(message: str, code: int = 1) -> None:
    print("aifull: " + message, file=sys.stderr)
    raise SystemExit(code)


def atomic_private_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    if os.name != "nt":
        temp.chmod(0o600)
    os.replace(temp, path)


def default_config(claude_root: str | None = None, codex_root: str | None = None,
                   yolo: bool = False) -> dict:
    roots = {
        "claude": Path(claude_root).expanduser() if claude_root else APP_DIR / "profiles" / "claude",
        "codex": Path(codex_root).expanduser() if codex_root else APP_DIR / "profiles" / "codex",
    }
    return {
        "schema_version": 1,
        "dashboard_url": DASHBOARD_URL,
        "yolo": bool(yolo),
        "min_headroom_percent": 15,
        "prefer_current_when_healthy": True,
        "providers": {
            provider: {
                "command": [provider],
                "profiles": {
                    slot: {
                        "path": str(roots[provider] / ("claude" + slot if provider == "claude" else "account" + slot)),
                        "dashboard_account": ("claude" + slot if provider == "claude" else "account" + slot),
                    } for slot in SLOTS
                },
            } for provider in PROVIDERS
        },
    }


def init_config(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="aifull init")
    parser.add_argument("--claude-root", help="Existing dashboard runtime/claude folder or desired Claude profile parent")
    parser.add_argument("--codex-root", help="Existing dashboard runtime/accounts folder or desired Codex profile parent")
    parser.add_argument("--yolo", action="store_true", help="Enable both providers' permission-bypass flags")
    opts = parser.parse_args(args)
    if CONFIG_FILE.exists():
        print(f"Existing config preserved: {CONFIG_FILE}")
        return
    config = default_config(opts.claude_root, opts.codex_root, opts.yolo)
    atomic_private_json(CONFIG_FILE, config)
    print(f"Created local config: {CONFIG_FILE}")
    for provider in PROVIDERS:
        for slot in SLOTS:
            print(f"  {provider} {slot}: {config['providers'][provider]['profiles'][slot]['path']}")
    if opts.yolo:
        print("WARNING: YOLO enabled for BOTH providers. Run only in an isolated/trusted workspace.")
    print("Authenticate each slot with: aifull login-all")


def load_config() -> dict:
    if not CONFIG_FILE.is_file():
        error(f"missing config {CONFIG_FILE}; run 'aifull init --yolo' or setup script")
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1:
            raise ValueError("unsupported schema_version; expected 1")
        for provider in PROVIDERS:
            block = data["providers"][provider]
            cmd = block["command"]
            if not isinstance(cmd, list) or not cmd or not all(isinstance(s, str) and s for s in cmd):
                raise ValueError(f"{provider}.command must be a nonempty list")
            for slot in SLOTS:
                p = block["profiles"][slot]
                if not isinstance(p.get("path"), str) or not p["path"]:
                    raise ValueError(f"{provider} profile {slot} must have path")
                if not isinstance(p.get("dashboard_account"), str) or not p["dashboard_account"]:
                    raise ValueError(f"{provider} profile {slot} must have dashboard_account")
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        error(f"invalid config: {exc}")


def profile_path(config: dict, provider: str, slot: str) -> Path:
    return Path(os.path.expandvars(config["providers"][provider]["profiles"][slot]["path"])).expanduser().resolve()


def profile_env(config: dict, provider: str, slot: str) -> dict[str, str]:
    env = os.environ.copy()
    for key in AUTH_OVERRIDES[provider]:
        env.pop(key, None)  # Prefer the interactive subscription login stored inside this profile.
    env["CLAUDE_CONFIG_DIR" if provider == "claude" else "CODEX_HOME"] = str(profile_path(config, provider, slot))
    return env


def cli_binary(config: dict, provider: str) -> list[str]:
    parts = config["providers"][provider]["command"]
    executable = shutil.which(parts[0]) or (parts[0] if Path(parts[0]).is_file() else None)
    if not executable:
        error(f"{provider} CLI not found ('{parts[0]}'). Install the official CLI; see README.")
    return [executable, *parts[1:]]


def login(config: dict, provider: str, slot: str, check: bool = False) -> int:
    p = profile_path(config, provider, slot)
    p.mkdir(parents=True, exist_ok=True)
    print(f"\n[{provider} account {slot}] {p}", flush=True)
    cmd = cli_binary(config, provider)
    cmd += (["auth", "status", "--text"] if check else ["auth", "login"]) if provider == "claude" else (["login", "status"] if check else ["login"])
    return subprocess.call(cmd, env=profile_env(config, provider, slot))


def dashboard_snapshot(config: dict) -> dict:
    url = config.get("dashboard_url") or DASHBOARD_URL
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise ValueError("dashboard_url must be HTTP(S)")
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "ai-cli-pool/1.0"})
    with urlopen(req, timeout=6) as resp:
        data = json.load(resp)
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), list):
        raise ValueError("dashboard missing accounts[]")
    return data


def quotas(config: dict, provider: str, dashboard: dict) -> dict[str, dict]:
    available = {}
    for item in dashboard.get("accounts", []):
        if not isinstance(item, dict) or item.get("provider") != provider:
            continue
        for slot in SLOTS:
            if item.get("account") == config["providers"][provider]["profiles"][slot]["dashboard_account"]:
                available[slot] = item
    return available


def percentage(item: dict, window: str) -> str:
    w = item.get(window)
    value = w.get("remainingPercent") if isinstance(w, dict) else None
    return f"{value:.0f}%" if isinstance(value, (int, float)) else "n/a"


def headroom(item: dict) -> float:
    try:
        return max(0, min(100, float(item.get("headroom", 0))))
    except (TypeError, ValueError):
        return 0


def show_status(config: dict, provider_filter: str | None = None) -> None:
    data = dashboard_snapshot(config)
    print("Cached quota snapshot:", config.get("dashboard_url", DASHBOARD_URL))
    print("Note: local login accounts must match the corresponding dashboard slot.")
    for provider in PROVIDERS:
        if provider_filter and provider != provider_filter:
            continue
        rows = quotas(config, provider, data)
        recommended = data.get("recommended") or {}
        print(f"\n{provider.upper()}   recommended: {recommended.get(provider, '-') if isinstance(recommended, dict) else '-'}")
        print(f"{'Slot':<7}{'Status':<14}{'5h':<10}{'Weekly':<10}Account")
        for slot in SLOTS:
            item = rows.get(slot, {})
            print(f"{slot:<7}{item.get('status', 'missing'):<14}{percentage(item, 'fiveHour'):<10}{percentage(item, 'weekly'):<10}{item.get('account', '-')}")


def choose_slot(config: dict, provider: str, forced: str | None,
                current: str | None, dashboard: dict | None) -> tuple[str, str]:
    if forced:
        return forced, "manually selected"
    if dashboard is None:
        return (current, "dashboard unavailable; reuse prior slot") if current in SLOTS else ("1", "dashboard unavailable; fallback slot 1")
    records = quotas(config, provider, dashboard)
    threshold = float(config.get("min_headroom_percent", 15))

    def eligible(slot: str) -> bool:
        a = records.get(slot) or {}
        return a.get("status") == "ready" and not a.get("stale", False) and headroom(a) > threshold

    if config.get("prefer_current_when_healthy", True) and current in SLOTS and eligible(current):
        return current, "current slot healthy"
    suggested = dashboard.get("recommended") or {}
    rec_id = suggested.get(provider) if isinstance(suggested, dict) else None
    for slot in SLOTS:
        wanted = config["providers"][provider]["profiles"][slot]["dashboard_account"]
        if rec_id == f"{provider}:{wanted}" and eligible(slot):
            return slot, "dashboard recommendation"
    candidates = [slot for slot in SLOTS if eligible(slot)]
    if candidates:
        return max(candidates, key=lambda s: headroom(records[s])), "maximum remaining quota"
    error(f"no healthy {provider} slot in quota dashboard. See 'aifull status {provider}', or force a slot explicitly.")


def project_state_path(project: Path) -> Path:
    key = hashlib.sha256(os.path.normcase(str(project)).encode("utf-8")).hexdigest()[:24]
    return STATE_DIR / (key + ".json")


def load_project_state(project: Path) -> dict:
    try:
        state = json.loads(project_state_path(project).read_text(encoding="utf-8"))
        return state if state.get("project") == str(project) else {"project": str(project), "sessions": {}}
    except (OSError, ValueError, TypeError):
        return {"project": str(project), "sessions": {}}


def save_project_state(project: Path, state: dict) -> None:
    state["updated_at"] = int(time.time())
    atomic_private_json(project_state_path(project), state)


@contextlib.contextmanager
def project_lock(project: Path):
    """One launcher-managed agent at a time per working directory."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    handle_path = project_state_path(project).with_suffix(".lock")
    with handle_path.open("a+b") as file:
        file.seek(0, os.SEEK_END)
        if file.tell() == 0:
            file.write(b"0")
            file.flush()
        file.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                error("this project is already running in another ai-cli-pool terminal")
            try:
                yield
            finally:
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                error("this project is already running in another ai-cli-pool terminal")
            try:
                yield
            finally:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def latest_claude_session(config: dict, project: Path, slot: str) -> tuple[str, float] | None:
    """Find this project's transcript, tolerating Windows path-encoding variants.

    Claude's project directory encoding can differ between CLI releases and
    Windows path formats. Prefer the exact directory; on fallback, verify that
    the recent transcript's own `cwd` metadata matches the project before use.
    """
    root = profile_path(config, "claude", slot) / "projects"
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(project))
    preferred = root / slug
    folders = [preferred] if preferred.is_dir() else []
    if root.is_dir():
        folders.extend(p for p in root.iterdir() if p.is_dir() and p != preferred)
    choices: list[tuple[str, float]] = []
    for folder in folders:
        for path in folder.glob("*.jsonl"):
            try:
                mtime = path.stat().st_mtime
                if folder == preferred:
                    choices.append((str(path), mtime))
                    continue
                # Claude transcripts contain cwd on JSON lines. Only read a few
                # records, never print or upload their content.
                with path.open("r", encoding="utf-8") as source:
                    for _, line in zip(range(12), source):
                        try:
                            entry = json.loads(line)
                        except (json.JSONDecodeError, ValueError):
                            continue
                        cwd = entry.get("cwd") if isinstance(entry, dict) else None
                        if isinstance(cwd, str) and Path(cwd).resolve() == project:
                            choices.append((str(path), mtime))
                            break
            except (OSError, ValueError):
                continue
    return max(choices, key=lambda item: item[1]) if choices else None


def latest_codex_session(config: dict, project: Path, slot: str) -> tuple[str, float] | None:
    """Inspect Codex rollout metadata (not credentials or message contents)."""
    root = profile_path(config, "codex", slot) / "sessions"
    if not root.exists():
        return None
    candidates = []
    for file in root.rglob("rollout-*.jsonl"):
        try:
            modified = file.stat().st_mtime
            with file.open("r", encoding="utf-8") as stream:
                for _, line in zip(range(6), stream):
                    item = json.loads(line)
                    if item.get("type") != "session_meta":
                        continue
                    meta = item.get("payload") or {}
                    if Path(str(meta.get("cwd", ""))).resolve() == project and isinstance(meta.get("id"), str):
                        candidates.append((meta["id"], modified))
                    break
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return max(candidates, key=lambda item: item[1]) if candidates else None


def find_session(config: dict, provider: str, project: Path, slot: str) -> tuple[str, float] | None:
    return latest_claude_session(config, project, slot) if provider == "claude" else latest_codex_session(config, project, slot)


def is_our_claude_path(config: dict, value: str) -> bool:
    try:
        source = Path(value).resolve(strict=True)
        return source.suffix == ".jsonl" and any(source.is_relative_to(profile_path(config, "claude", s)) for s in SLOTS)
    except (ValueError, OSError):
        return False


def git_text(project: Path, *args: str) -> str:
    if not shutil.which("git"):
        return "(Git unavailable)"
    proc = subprocess.run(["git", *args], cwd=project, text=True, capture_output=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else "(Unavailable)"


def create_handoff(project: Path) -> Path:
    target = project / HANDOFF_FILE
    if target.exists():
        print(f"Handoff exists and was NOT overwritten: {target}")
        return target
    target.write_text(
        "# AI CLI Pool: portable project handoff\n\n"
        "> Fill in the task details and review this document for secrets before committing it.\n"
        "> This summary is portable; raw Claude/Codex session history is not synced.\n\n"
        "## Current goal\n\n- TODO: What are you working on?\n\n"
        "## Decisions / progress\n\n- TODO: What has been changed and why?\n\n"
        "## Next actions\n\n- TODO: Exact next steps for the next agent.\n\n"
        "## Git snapshot\n\n"
        f"- Branch: `{git_text(project, 'branch', '--show-current')}`\n"
        f"- HEAD: `{git_text(project, 'rev-parse', '--short', 'HEAD')}`\n\n"
        "```text\n" + (git_text(project, "status", "--short") or "clean working tree") + "\n```\n",
        encoding="utf-8",
    )
    print(f"Created {target}. Complete TODOs, review for secrets, then optionally commit in the PROJECT repository.")
    return target


def launch(config: dict, provider: str, forced: str | None = None,
           fresh: bool = False, extra: list[str] | None = None) -> int:
    project = Path.cwd().resolve()
    with project_lock(project):
        state = load_project_state(project)
        last = state.get("sessions", {}).get(provider, {})
        current_slot = last.get("slot") if last.get("slot") in SLOTS else None
        dashboard = None
        if forced is None:
            try:
                dashboard = dashboard_snapshot(config)
            except (HTTPError, URLError, OSError, ValueError, TimeoutError) as exc:
                print(f"Quota dashboard unavailable: {exc}; using locally known slot.", file=sys.stderr)
        slot, reason = choose_slot(config, provider, forced, current_slot, dashboard)
        command = cli_binary(config, provider)
        yolo = bool(config.get("yolo", False))
        existing = None
        if not fresh:
            prev_session = last.get("session")
            if provider == "claude" and isinstance(prev_session, str) and is_our_claude_path(config, prev_session):
                existing = (current_slot, prev_session)
            elif provider == "codex" and current_slot == slot and isinstance(prev_session, str) and re.fullmatch(r"[a-fA-F0-9-]{36}", prev_session):
                existing = (slot, prev_session)
            else:
                found = find_session(config, provider, project, slot)
                if found:
                    existing = (slot, found[0])
        print(f"\nAI CLI Pool | {provider.upper()} account {slot} | {reason}", flush=True)
        print(f"Project: {project}\nProfile: {profile_path(config, provider, slot)}", flush=True)
        switched = current_slot in SLOTS and current_slot != slot
        previous_provider = (state.get("active") or {}).get("provider")
        handoff = project / HANDOFF_FILE
        should_read_handoff = handoff.is_file() and (fresh or not existing or previous_provider != provider)
        if provider == "claude":
            if yolo:
                command.append("--dangerously-skip-permissions")
            if existing:
                origin, transcript = existing
                command += ["--resume", transcript]
                if origin != slot:
                    command.append("--fork-session")
                    print("Forking Claude transcript to selected account", flush=True)
            if should_read_handoff:
                command += ["--append-system-prompt", f"Read {HANDOFF_FILE} in this working directory to recover the current task. Verify against project files."]
        else:
            if existing and existing[0] == slot:
                command += ["resume", existing[1]]
                print("Resuming Codex session within the same account", flush=True)
            elif switched:
                print("Codex account changed: new conversation (Codex does not share session history across account folders).", flush=True)
                if not handoff.is_file():
                    print(f"Tip: create and fill {HANDOFF_FILE} using 'aifull handoff' before switching.", flush=True)
            if yolo:
                command.append("--dangerously-bypass-approvals-and-sandbox")
            if should_read_handoff and not existing and not (extra or []):
                command.append(f"Read {HANDOFF_FILE} in this project, check its claims against current files, then continue the next action. Ask me what to do if TODOs are incomplete.")
        command.extend(extra or [])
        if yolo:
            print("WARNING: YOLO enabled; the agent may run arbitrary commands and edit outside the project.", flush=True)
        began = time.time()
        result = subprocess.call(command, env=profile_env(config, provider, slot))
        new_session = find_session(config, provider, project, slot)
        if new_session and new_session[1] >= began - 3:
            state.setdefault("sessions", {})[provider] = {"slot": slot, "session": new_session[0]}
        elif not fresh and existing and existing[0] == slot:
            state.setdefault("sessions", {})[provider] = {"slot": slot, "session": existing[1]}
        else:
            # Do not accidentally resume a stale session after a failed/incomplete fork.
            state.setdefault("sessions", {}).pop(provider, None)
        state["active"] = {"provider": provider, "slot": slot}
        save_project_state(project, state)
        return result


def doctor(config: dict) -> int:
    print("AI CLI Pool diagnostics")
    print(f"Configuration: {CONFIG_FILE}\nYOLO: {'enabled' if config.get('yolo') else 'disabled'}")
    for provider in PROVIDERS:
        try:
            binary = cli_binary(config, provider)[0]
            print(f"{provider}: executable {binary}")
        except SystemExit:
            print(f"{provider}: CLI missing")
        for slot in SLOTS:
            print(f"  {slot}: {profile_path(config, provider, slot)}")
    print("Run 'aifull auth claude all' or 'aifull auth codex all' to verify login status.")
    return 0


def usage() -> None:
    print("""AI CLI Pool - Windows and Ubuntu, 3 accounts per provider

  aifull init --yolo                 Create config (if absent), enable YOLO for both
  aifull init --claude-root PATH --codex-root PATH --yolo
  aifull login-all                   Log into all 6 accounts once (interactive)
  aifull login claude 1|2|3|all      Log into one/all Claude accounts
  aifull login codex 1|2|3|all       Log into one/all Codex accounts
  aifull auth claude|codex 1|2|3|all  Inspect logins
  aifull status [claude|codex]       Cached quota from token.openjvspace.com
  aifull doctor                      Show CLI and profile paths
  aifull claude [1|2|3|new]         Auto-select or force Claude account
  aifull codex [1|2|3|new]          Auto-select or force Codex account
  aifull claude 2 -- --model sonnet  Pass extra arguments to a CLI
  aifull codex 1 -- -m MODEL         Pass extra arguments to a CLI
  claudefull [1|2|3|new]            Alias to aifull claude
  codexfull [1|2|3|new]             Alias to aifull codex
  aifull handoff                    Make portable Git-friendly project handoff
  aifull mode yolo|safe             Toggle bypass for both providers
  aifull config                     Display local configuration path

Session continuity: Claude can fork a local transcript across profiles.
Codex resumes in the same profile. Across profiles/providers/machines,
use Git + the reviewed handoff file; exact histories are not compatible.
""")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        usage()
        return 0
    if argv[0] == "init":
        init_config(argv[1:])
        return 0
    config = load_config()
    command = argv[0]
    if command in PROVIDERS:
        if len(argv) > 1 and argv[1] in ("-h", "--help", "help"):
            usage()
            return 0
        rest = argv[1:]
        mode = rest[0] if rest and rest[0] in (*SLOTS, "new", "auto") else "auto"
        if mode != "auto" or (rest and rest[0] == "auto"):
            rest = rest[1:]
        if rest and rest[0] != "--":
            error("pass provider arguments after '--', e.g. aifull codex 2 -- -m MODEL")
        return launch(config, command, forced=(mode if mode in SLOTS else None), fresh=(mode == "new"), extra=rest[1:] if rest else [])
    if command == "config":
        print(CONFIG_FILE)
    elif command == "status":
        if len(argv) > 2 or (len(argv) == 2 and argv[1] not in PROVIDERS):
            error("usage: aifull status [claude|codex]")
        try:
            show_status(config, argv[1] if len(argv) == 2 else None)
        except (HTTPError, URLError, OSError, ValueError, TimeoutError) as exc:
            error(f"quota unavailable: {exc}")
    elif command in ("login", "auth"):
        if len(argv) != 3 or argv[1] not in PROVIDERS or argv[2] not in (*SLOTS, "all"):
            error(f"usage: aifull {command} claude|codex 1|2|3|all")
        codes = [login(config, argv[1], s, check=(command == "auth")) for s in (SLOTS if argv[2] == "all" else (argv[2],))]
        return int(any(codes))
    elif command == "login-all":
        for provider in PROVIDERS:
            for slot in SLOTS:
                if login(config, provider, slot):
                    error(f"login failed for {provider} {slot}. Retry with: aifull login {provider} {slot}")
    elif command == "doctor":
        return doctor(config)
    elif command == "handoff":
        create_handoff(Path.cwd().resolve())
    elif command == "mode":
        if len(argv) != 2 or argv[1] not in ("yolo", "safe"):
            error("usage: aifull mode yolo|safe")
        config["yolo"] = argv[1] == "yolo"
        atomic_private_json(CONFIG_FILE, config)
        print(f"YOLO {'ENABLED for both providers - use a trusted workspace' if config['yolo'] else 'disabled'}")
    else:
        error(f"unknown command '{command}'. Run aifull help")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
