# NotebookLM Connector

![NotebookLM Connector — download, connect, and ask your Google NotebookLM notebooks from inside Claude](assets/hero.png)

Talk to your **Google NotebookLM** notebooks from inside **Claude**. Ask questions answered only from your own sources (with citations), add sources, and generate Audio Overviews, reports, quizzes, and more — all from a normal chat.

## ⬇️ Install (Claude Desktop)

### [**Download NotebookLM-Connector.mcpb**](https://github.com/asimhafeezz/notebooklm-connector/releases/latest)

1. **Download** the file above.
2. **Double-click** it → Claude Desktop opens → click **Install**.
3. In a chat, type **“Connect my NotebookLM”** → pick your Google account when asked.
4. Type **“List my notebooks.”** That’s it.

> **Needs Python 3.12** on your computer first.
> Mac: `brew install python@3.12` · Windows: [python.org](https://www.python.org/downloads/). Nothing else to set up.
>
> No password is ever typed — the connector uses the Google account you’re already signed into in your browser. On Mac, click **Allow** on the one-time Keychain popup.

## What you can ask Claude to do

- *“Ask my Thesis notebook: what counterarguments do the sources discuss?”*
- *“Create a notebook called ‘Competitor research’ and add these three URLs as sources.”*
- *“Make an audio overview of my Onboarding notebook about deployment, then save it to my Desktop.”*
- *“Give me a quiz from my Biology notebook.”*

Under the hood that’s **13 tools**: connect/login, list & create notebooks, add sources (URLs, YouTube, text, files), ask questions with citations, and generate + download Studio content (audio, video, reports, quizzes, flashcards, mind maps, slide decks, infographics, data tables).

## Good to know

- **Sessions last ~2–4 weeks.** When it stops working, just say “Connect my NotebookLM” again.
- **Free NotebookLM accounts** allow about 50 questions per day.
- **It’s your own account** — use it as you normally would.
- **Unofficial** — this uses NotebookLM’s internal API (Google has no public one). It’s reliable but can break if Google changes things; updating fixes it.

---

## Other apps

**Claude Code:** run `./install.sh` in this folder — it installs everything and registers the server.

**Cursor, Codex, Antigravity, and other MCP clients:** add this server with the command
`uv --directory /path/to/notebooklm-connector run notebooklm-connector`.
*(A simpler `uvx notebooklm-connector` one-liner is coming once it’s published to PyPI.)*

## For developers

```bash
uv sync                                                            # install
uv run notebooklm-connector                                        # run the server
npx @modelcontextprotocol/inspector uv run notebooklm-connector    # test tools interactively
npx @anthropic-ai/mcpb pack . dist/NotebookLM-Connector.mcpb       # rebuild the installer
```

**How it works:** Claude ↔ this MCP server ↔ [notebooklm-py](https://github.com/teng-lin/notebooklm-py) ↔ NotebookLM’s internal API. Auth is your browser’s existing Google session, read locally; nothing is sent anywhere except to NotebookLM. Multiple Google accounts: `uv run notebooklm login --profile work`, then set `NOTEBOOKLM_PROFILE=work` in the server’s env.

MIT licensed.
