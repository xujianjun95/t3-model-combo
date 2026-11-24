#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/xujianjun95/t3-model-combo.git"
SKILL_NAME="t3-model-combo"
SHARE_DIR="${HOME}/.local/share/${SKILL_NAME}"

TARGET_DIR=""
UNINSTALL=0
USE_COPY=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install or uninstall the ${SKILL_NAME} Agent Skill for T3 Code and compatible agents.

Options:
  --target <dir>   Install into (or uninstall from) a specific directory
  --copy           Copy skill files instead of creating symlinks
  --uninstall      Remove installed ${SKILL_NAME} skill links/copies
  -h, --help       Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        echo "Error: --target requires a directory path." >&2
        exit 1
      fi
      TARGET_DIR="$2"
      shift 2
      ;;
    --uninstall)
      UNINSTALL=1
      shift
      ;;
    --copy)
      USE_COPY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

check_python() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required but was not found in PATH." >&2
    exit 1
  fi

  if ! python3 -c 'import sys, json, urllib.request, pathlib, argparse; assert sys.version_info >= (3, 9)' >/dev/null 2>&1; then
    local py_ver
    py_ver="$(python3 --version 2>&1 || true)"
    echo "Warning: Python 3.9+ with standard library is recommended (detected: ${py_ver})." >&2
  fi
}

resolve_target_path() {
  local raw="$1"
  raw="${raw%/}"
  if [[ "$(basename "$raw")" == "${SKILL_NAME}" ]]; then
    printf '%s\n' "$raw"
  else
    printf '%s/%s\n' "$raw" "${SKILL_NAME}"
  fi
}

collect_targets() {
  if [[ -n "$TARGET_DIR" ]]; then
    resolve_target_path "$TARGET_DIR"
    return
  fi

  local candidates=(
    "${HOME}/.agents"
    "${HOME}/.codex"
    "${HOME}/.claude"
    "${HOME}/.cursor"
  )

  local found=()
  local base
  for base in "${candidates[@]}"; do
    if [[ -d "$base" || -d "${base}/skills" ]]; then
      found+=("${base}/skills/${SKILL_NAME}")
    fi
  done

  # Also detect T3 Code Antigravity provider skill directories if present
  local ag_dir
  for ag_dir in "${HOME}/.t3/userdata/providers/antigravity"/*/config/skills; do
    if [[ -d "$ag_dir" ]]; then
      found+=("${ag_dir}/${SKILL_NAME}")
    fi
  done

  if [[ ${#found[@]} -eq 0 ]]; then
    found+=("${HOME}/.agents/skills/${SKILL_NAME}")
  fi

  printf '%s\n' "${found[@]}"
}

remove_target() {
  local dst="$1"
  if [[ -L "$dst" || -e "$dst" ]]; then
    rm -rf "$dst"
    echo "Removed: $dst"
    return 0
  fi
  return 1
}

if [[ "$UNINSTALL" -eq 1 ]]; then
  removed_any=0
  while IFS= read -r dst; do
    if remove_target "$dst"; then
      removed_any=1
    fi
  done < <(collect_targets)

  if [[ -z "$TARGET_DIR" && -d "$SHARE_DIR" ]]; then
    rm -rf "$SHARE_DIR"
    echo "Removed cloned repo: $SHARE_DIR"
    removed_any=1
  fi

  if [[ "$removed_any" -eq 0 ]]; then
    echo "No installed ${SKILL_NAME} skill directories were found."
  else
    echo "Uninstall complete."
  fi
  exit 0
fi

check_python

SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

SOURCE_DIR=""
if [[ -n "$SCRIPT_DIR" && -f "${SCRIPT_DIR}/SKILL.md" && -d "${SCRIPT_DIR}/scripts" ]]; then
  SOURCE_DIR="$SCRIPT_DIR"
elif [[ -f "./SKILL.md" && -d "./scripts" ]]; then
  SOURCE_DIR="$(pwd)"
else
  if ! command -v git >/dev/null 2>&1; then
    echo "Error: git is required to clone ${REPO_URL} when running remotely." >&2
    exit 1
  fi
  mkdir -p "$(dirname "$SHARE_DIR")"
  if [[ -d "${SHARE_DIR}/.git" ]]; then
    echo "Updating existing checkout in ${SHARE_DIR}..."
    git -C "$SHARE_DIR" pull --ff-only
  else
    echo "Cloning ${REPO_URL} into ${SHARE_DIR}..."
    rm -rf "$SHARE_DIR"
    git clone --depth 1 "$REPO_URL" "$SHARE_DIR"
  fi
  SOURCE_DIR="$SHARE_DIR"
fi

INSTALLED=()
while IFS= read -r dst; do
  mkdir -p "$(dirname "$dst")"
  if [[ "$USE_COPY" -eq 1 ]]; then
    rm -rf "$dst"
    mkdir -p "$dst"
    cp -R "${SOURCE_DIR}/." "$dst"
    rm -rf "${dst}/.git"
    INSTALLED+=("$dst (copied)")
  else
    if [[ -e "$dst" && ! -L "$dst" ]]; then
      rm -rf "$dst"
    fi
    ln -sfn "$SOURCE_DIR" "$dst"
    INSTALLED+=("$dst -> $SOURCE_DIR")
  fi
done < <(collect_targets)

echo ""
echo "t3-model-combo installed successfully!"
echo "Source: ${SOURCE_DIR}"
echo "Targets:"
for item in "${INSTALLED[@]}"; do
  echo "  - ${item}"
done
echo ""
echo "在 T3 Code 里重启会话即可通过 / 或 \$ 使用 t3-model-combo。"
