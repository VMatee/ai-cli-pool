#!/usr/bin/env bash
# Ubuntu/macOS setup. Uses only Python 3 standard library.
set -euo pipefail

show_help() {
  cat <<'EOF'
Usage: ./setup.sh [--login-all] [--safe] [--claude-root PATH] [--codex-root PATH]
  --login-all       Open six separate official CLI login flows (interactive)
  --safe            Disable YOLO/permission bypass for both CLIs
  --claude-root     Parent dir containing claude1, claude2, claude3 profiles
  --codex-root      Parent dir containing account1, account2, account3 profiles

Default is YOLO, as requested. Only use in an isolated/trusted environment.
EOF
}

login_all=0
safe=0
claude_root=""
codex_root=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --login-all) login_all=1; shift ;;
    --safe) safe=1; shift ;;
    --claude-root|--codex-root)
      [[ $# -ge 2 ]] || { show_help; exit 2; }
      if [[ "$1" == "--claude-root" ]]; then claude_root="$2"; else codex_root="$2"; fi
      shift 2 ;;
    -h|--help) show_help; exit 0 ;;
    *) echo "Unknown option: $1" >&2; show_help; exit 2 ;;
  esac
done

command -v python3 >/dev/null || { echo "Install Python 3.9+ and retry." >&2; exit 1; }
command -v git >/dev/null || echo "NOTE: Git is recommended for transferring projects between computers."

root="$HOME/.ai-cli-pool"
mkdir -p "$root/app" "$HOME/.local/bin"
cp "$(dirname "$(realpath "$0")")/aifull.py" "$root/app/aifull.py"
chmod 700 "$root/app/aifull.py"

for command_name in aifull claudefull codexfull; do
  case "$command_name" in
    aifull) prefix='' ;;
    claudefull) prefix='claude' ;;
    codexfull) prefix='codex' ;;
  esac
  cat > "$HOME/.local/bin/$command_name" <<EOF
#!/usr/bin/env bash
exec python3 "\$HOME/.ai-cli-pool/app/aifull.py" $prefix "\$@"
EOF
  chmod 755 "$HOME/.local/bin/$command_name"
done

args=()
[[ -z "$claude_root" ]] || args+=(--claude-root "$claude_root")
[[ -z "$codex_root" ]] || args+=(--codex-root "$codex_root")
if (( safe )); then
  python3 "$root/app/aifull.py" init "${args[@]}"
  python3 "$root/app/aifull.py" mode safe
else
  python3 "$root/app/aifull.py" init "${args[@]}" --yolo
  python3 "$root/app/aifull.py" mode yolo
fi

if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
  if [[ -f "$HOME/.bashrc" ]] && ! grep -Fq 'export PATH="$HOME/.local/bin:$PATH"' "$HOME/.bashrc"; then
    printf '\n# AI CLI Pool commands\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.bashrc"
  fi
  export PATH="$HOME/.local/bin:$PATH"
  echo "Added ~/.local/bin to current PATH and ~/.bashrc (open new terminal after install)."
fi

for provider in claude codex; do
  if ! command -v "$provider" >/dev/null 2>&1; then
    echo "NOTE: '$provider' CLI is not installed/found. See README installation links."
  fi
done

if (( login_all )); then
  python3 "$root/app/aifull.py" login-all
fi

printf '\nInstalled: aifull, claudefull, codexfull\n'
printf 'Try: aifull doctor; aifull status; claudefull; codexfull\n'
