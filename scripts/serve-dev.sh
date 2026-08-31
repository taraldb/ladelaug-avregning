#!/usr/bin/env bash
# Run the dev server with WeasyPrint's Homebrew native libs on the loader path,
# so the PDF report endpoints work outside Docker on macOS. Harmless elsewhere.
#
#   brew install pango        # one-time
#   scripts/serve-dev.sh
set -euo pipefail
cd "$(dirname "$0")/.."

for d in /opt/homebrew/lib /usr/local/lib; do
  [ -d "$d" ] && export DYLD_FALLBACK_LIBRARY_PATH="$d${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}"
done

exec uv run python -m ladelaug_avregning "${@:-serve}"
