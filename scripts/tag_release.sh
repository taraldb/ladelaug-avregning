#!/usr/bin/env bash
# Creates the git tag vX.Y.Z matching the repo-root VERSION file, which is this
# project's single source of truth for the version (kept in lockstep with
# pyproject.toml in the same commit).
#
# Usage:
#   scripts/tag_release.sh [-m "message"] [--push] [--dry-run]
#
# Refuses to run with uncommitted changes. Never pushes unless --push is passed.

set -euo pipefail

MESSAGE=""
PUSH=false
DRY_RUN=false

usage() {
  cat <<'EOF'
Usage: scripts/tag_release.sh [-m "message"] [--push] [--dry-run]

  -m, --message TEXT  Annotated tag message (default: "Release vX.Y.Z" plus the
                       one-line log since the previous tag)
  --push              Push the new tag to origin after creating it
  --dry-run           Print what would happen without creating anything
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--message) MESSAGE="$2"; shift 2 ;;
    --push) PUSH=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "Not inside a git repository." >&2
  exit 1
}
cd "$repo_root"

if [[ ! -f VERSION ]]; then
  echo "No VERSION file at repo root." >&2
  exit 1
fi
version="$(tr -d '[:space:]' < VERSION)"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "VERSION does not look like X.Y.Z: '$version'" >&2
  exit 1
fi
next_tag="v${version}"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree has uncommitted changes - commit or stash first." >&2
  git status --short >&2
  exit 1
fi

if git rev-parse "$next_tag" >/dev/null 2>&1; then
  echo "Tag $next_tag already exists - bump VERSION first." >&2
  exit 1
fi

prev_tag="$(git tag -l 'v*' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' \
  | sed -E 's/^v//' | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)"

if [[ -z "$MESSAGE" ]]; then
  if [[ -n "$prev_tag" ]]; then
    commits="$(git log "v${prev_tag}..HEAD" --oneline)"
  else
    commits="$(git log --oneline)"
  fi
  if [[ -z "$commits" ]]; then
    MESSAGE="Release $next_tag"
  else
    MESSAGE="$(printf 'Release %s\n\n%s\n' "$next_tag" "$commits")"
  fi
fi

echo "Next tag: $next_tag (from VERSION; previous: $( [[ -n "$prev_tag" ]] && echo "v$prev_tag" || echo none ))"
echo "---"
echo "$MESSAGE"
echo "---"

if $DRY_RUN; then
  echo "Dry run - nothing created."
  exit 0
fi

git tag -a "$next_tag" -m "$MESSAGE"
echo "Created annotated tag $next_tag at $(git rev-parse --short HEAD)."

if $PUSH; then
  git push origin "$next_tag"
  echo "Pushed."
else
  echo "Not pushed. To push: git push origin $next_tag"
fi
