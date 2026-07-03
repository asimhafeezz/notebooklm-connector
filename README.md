# NotebookLM Connector

[![PyPI](https://img.shields.io/pypi/v/notebooklm-connector?color=4f46e5)](https://pypi.org/project/notebooklm-connector/) [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

![NotebookLM Connector — install, connect, and ask your Google NotebookLM notebooks from inside any AI assistant](assets/hero.png)

Bring your **Google NotebookLM** notebooks into **any AI assistant that speaks [MCP](https://modelcontextprotocol.io)** — Claude, Cursor, Codex, Windsurf, Cline, and more. Ask questions answered only from your own sources (with citations), add sources, and generate Audio Overviews, reports, quizzes, and more — all from a normal chat.

## Install

Pick your app below. Then in a chat, say **“Connect my NotebookLM”**, choose your Google account, and you’re in — no password, ever.

> **One-time requirement:** the connector needs **Python 3.12** and **[uv](https://docs.astral.sh/uv/)** on the machine.
> Mac: `brew install python@3.12 uv` · Windows: [python.org](https://www.python.org/downloads/) + [uv install](https://docs.astral.sh/uv/getting-started/installation/).
> *(Claude Desktop’s `.mcpb` only needs Python — its runtime provides the rest.)*

### Claude Desktop — download & double-click

**[⬇️ Download NotebookLM-Connector.mcpb](https://github.com/asimhafeezz/notebooklm-connector/releases/latest)** → double-click it → **Install**. Done.

### Cursor — one click

[![Add to Cursor](https://cursor.com/deeplink/mcp-install-dark.svg)](https://cursor.com/install-mcp?name=notebooklm&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJub3RlYm9va2xtLWNvbm5lY3RvciJdfQ==)

### Codex — one line

```bash
codex mcp add notebooklm -- uvx notebooklm-connector
```

### Claude Code — one line

```bash
claude mcp add notebooklm -- uvx notebooklm-connector
```

### Google Antigravity

In the agent side panel: **⋯ → MCP Servers → Manage MCP Servers → View raw config**, then add the entry below. (Config file: `~/.gemini/config/mcp_config.json`.)

```json
{
  "mcpServers": {
    "notebooklm": { "command": "uvx", "args": ["notebooklm-connector"] }
  }
}
```

### Any other MCP client (Windsurf, Cline, …)

Add the same `mcpServers` entry shown above to the client’s MCP config.

Every non-Claude-Desktop option runs the same command, **`uvx notebooklm-connector`**, which fetches the connector [from PyPI](https://pypi.org/project/notebooklm-connector/) — nothing to clone.

## What you can ask

- *“Ask my Thesis notebook: what counterarguments do the sources discuss?”*
- *“Create a notebook called ‘Competitor research’ and add these three URLs as sources.”*
- *“Make an audio overview of my Onboarding notebook about deployment, then save it to my Desktop.”*
- *“Give me a quiz from my Biology notebook.”*

That’s **13 tools** under the hood: connect/login, list & create notebooks, add sources (URLs, YouTube, text, files), ask questions with citations, and generate + download Studio content (audio, video, reports, quizzes, flashcards, mind maps, slide decks, infographics, data tables).

## Good to know

- **No password, ever** — the connector reuses the Google account you’re already signed into in your browser. On Mac, approve the one-time Keychain popup.
- **Sessions last ~2–4 weeks.** When it stops working, just say “Connect my NotebookLM” again.
- **Free NotebookLM accounts** allow about 50 questions per day.
- **It’s your own account** — use it as you normally would.
- **Unofficial** — this uses NotebookLM’s internal API (Google has no public one). It’s reliable but can break if Google changes things; updating usually fixes it.

## How it works

```
Your AI assistant ──MCP──► notebooklm-connector ──► notebooklm-py ──► NotebookLM’s internal API
```

Auth is your browser’s existing Google session, read locally on your machine. Nothing is sent anywhere except to NotebookLM itself. It runs entirely on your computer.

## For developers

```bash
uv sync                                                            # install
uv run notebooklm-connector                                        # run the server
npx @modelcontextprotocol/inspector uv run notebooklm-connector    # test tools interactively
npx @anthropic-ai/mcpb pack . dist/NotebookLM-Connector.mcpb       # rebuild the .mcpb installer
```

Wraps [notebooklm-py](https://github.com/teng-lin/notebooklm-py). Multiple Google accounts: `uv run notebooklm login --profile work`, then set `NOTEBOOKLM_PROFILE=work` in the server’s env.

MIT licensed.
