# NotebookLM Connector

Connect **Google NotebookLM** to **Claude** — ask questions answered *only* from your own sources (with citations), manage notebooks, and generate Studio content (Audio Overviews, reports, quizzes, slide decks…) straight from a Claude conversation.

Ships as a one-file installable for Claude Desktop and an installer script for Claude Code.

### ⬇️ [Download the latest installer (NotebookLM-Connector.mcpb)](https://github.com/asimhafeezz/notebooklm-connector/releases/latest)

Download it, double-click, and Claude Desktop installs it. (Requires Python 3.12 on the machine.)

## Install

### Claude Desktop (easiest — double-click)

1. Get `notebooklm-connector.mcpb` (from `dist/`, or from whoever shared it with you)
2. Double-click it (or drag it onto Claude Desktop) → click **Install**
3. In a chat, say: **"Connect my NotebookLM"** — if several Google accounts are signed in to your browser, a native account-picker dialog appears; click yours. No password typed, ever. On macOS, approve the one-time Keychain prompt.
4. Say: **"List my notebooks"** — done.

> Requires Python 3.12+ available on the machine (macOS: `brew install python`; Windows: python.org installer). Claude Desktop's uv runtime handles everything else.

### Claude Code (CLI)

```bash
./install.sh
```

Installs dependencies, registers the MCP server in user scope, and prints the login instructions.

### Any other MCP client

```json
{
  "mcpServers": {
    "notebooklm": {
      "command": "uv",
      "args": ["--directory", "/path/to/notebooklm-connector", "run", "notebooklm-connector"]
    }
  }
}
```

## What Claude can do with it (12 tools)

| | Tools |
|---|---|
| Auth | `notebooklm_login` (browser-session or interactive), `notebooklm_auth_status` |
| Notebooks | `notebooklm_list_notebooks`, `notebooklm_create_notebook`, `notebooklm_get_notebook` |
| Sources | `notebooklm_add_source` (URLs, YouTube, text, local files) |
| Q&A | `notebooklm_ask` — source-grounded answers with citations and follow-up conversations |
| Studio | `notebooklm_generate`, `notebooklm_generation_status`, `notebooklm_list_artifacts`, `notebooklm_download_artifact` |
| Cleanup | `notebooklm_delete` |

### Example prompts

- "Create a notebook called 'Competitor research' and add these URLs as sources: …"
- "Ask my Thesis notebook: what counterarguments do the sources discuss?"
- "Generate an audio overview of my Onboarding notebook focused on deployment, then save it to my Desktop"

## How it works

Google offers no public NotebookLM API (only an enterprise one behind Google Cloud). This connector wraps [notebooklm-py](https://github.com/teng-lin/notebooklm-py), which speaks NotebookLM's **internal, undocumented API** using your own Google session cookies. Login never sees your password: it either copies the session from a browser you're already signed into, or captures it from a normal Google sign-in window. Everything runs locally; nothing is sent anywhere except to NotebookLM itself.

```
Claude ──MCP (stdio)──► notebooklm-connector ──notebooklm-py──► NotebookLM internal API
                                                    ▲
                                     Google session cookies from your browser
```

## Caveats

- **Unofficial API** — Google can change NotebookLM internals anytime. Fix is usually `uv sync --upgrade`.
- **Sessions expire** every ~2–4 weeks → just say "log in to NotebookLM" again.
- **Quotas** — free NotebookLM accounts allow ~50 chat queries/day.
- **Personal use** — this automates *your own* account; keep usage reasonable.

## Building the installable

```bash
npx @anthropic-ai/mcpb pack . dist/notebooklm-connector.mcpb
```

Share the resulting `.mcpb` file — recipients double-click it into Claude Desktop.

## Development

```bash
uv sync
uv run notebooklm-connector                                        # run over stdio
npx @modelcontextprotocol/inspector uv run notebooklm-connector    # interactive testing
```

Multiple Google accounts: `uv run notebooklm login --profile work`, then set `NOTEBOOKLM_PROFILE=work` in the server's env.
