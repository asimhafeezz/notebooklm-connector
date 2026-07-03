#!/usr/bin/env bash
# NotebookLM Connector — installer for Claude Code (CLI) users.
# Usage: ./install.sh   (run from the project directory)
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> NotebookLM Connector installer"

if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv (Python package manager)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "==> Installing dependencies..."
(cd "$DIR" && uv sync)

if command -v claude >/dev/null 2>&1; then
  echo "==> Registering MCP server with Claude Code (user scope)..."
  claude mcp add --scope user notebooklm -- uv --directory "$DIR" run notebooklm-connector || true
else
  echo "!! Claude Code CLI not found — register manually later with:"
  echo "   claude mcp add --scope user notebooklm -- uv --directory \"$DIR\" run notebooklm-connector"
fi

cat <<'DONE'

==> Installed.

Next step — authenticate (pick one):
  a) Just ask Claude: "log in to NotebookLM"  (reads your browser's Google session)
  b) Or run:          uv run notebooklm login  (opens a sign-in window)

Then ask Claude: "check my NotebookLM auth status".
DONE
