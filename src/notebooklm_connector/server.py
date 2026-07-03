#!/usr/bin/env python3
"""MCP server connecting Google NotebookLM to Claude.

Wraps the notebooklm-py client (reverse-engineered NotebookLM internal API)
and exposes a small, focused set of tools: notebook CRUD, source management,
source-grounded Q&A with citations, and Studio content generation
(audio overviews, reports, quizzes, slide decks, ...).
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field, create_model

from notebooklm import (
    ArtifactType,
    AuthError,
    ReportFormat,
)
from notebooklm import paths as nlm_paths

from .client import LOGIN_HINT, format_error, get_client, profile, reset_client

mcp = FastMCP("notebooklm_mcp")

# ---------------------------------------------------------------------------
# formatting helpers
# ---------------------------------------------------------------------------


def _fmt_dt(dt: Any) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "unknown"


def _fmt_notebook_line(nb: Any) -> str:
    return f"- **{nb.title}** (`{nb.id}`) — {nb.sources_count} sources, created {_fmt_dt(nb.created_at)}"


def _fmt_source_line(s: Any) -> str:
    status = getattr(s.status, "name", str(s.status)).lower()
    url = f" — {s.url}" if s.url else ""
    return f"- **{s.title or 'Untitled'}** (`{s.id}`) — status: {status}{url}"


def _fmt_generation(status: Any) -> str:
    lines = [
        f"- task_id: `{status.task_id}`",
        f"- status: {status.status}",
    ]
    if status.url:
        lines.append(f"- url: {status.url}")
    if status.error:
        lines.append(f"- error: {status.error}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# thorough-mode (auto coverage follow-up) configuration and helpers
# ---------------------------------------------------------------------------


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


DEFAULT_THOROUGH = _bool_env("NOTEBOOKLM_THOROUGH", False)
try:
    DEFAULT_MAX_FOLLOWUPS = max(1, min(5, int(os.environ.get("NOTEBOOKLM_MAX_FOLLOWUPS", "3"))))
except ValueError:
    DEFAULT_MAX_FOLLOWUPS = 3


def _collect_citations(result: Any, by_source: dict[str, list[str]]) -> None:
    """Fold an answer's cited passages into a source_id -> snippets map."""
    for ref in result.references or []:
        snippet = (ref.cited_text or "").strip().replace("\n", " ")
        if len(snippet) > 200:
            snippet = snippet[:200] + "…"
        by_source.setdefault(ref.source_id, [])
        if snippet and snippet not in by_source[ref.source_id]:
            by_source[ref.source_id].append(snippet)


def _render_citations(by_source: dict[str, list[str]], titles: dict[str, str]) -> list[str]:
    if not by_source:
        return []
    lines = ["", "## Citations"]
    for sid, snippets in by_source.items():
        lines.append(f"- **{titles.get(sid, sid)}** (`{sid}`)")
        lines += [f'  - "{sn}"' for sn in snippets[:3]]
    return lines


def _parse_followups(text: str, limit: int) -> list[str]:
    """Extract follow-up questions from NotebookLM's gap-analysis reply."""
    text = (text or "").strip()
    if not text or text.upper().startswith("NONE"):
        return []
    questions: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"^[\-\*\d\.\)\(\s]+", "", line).strip()
        if len(line) > 8 and line not in questions:
            questions.append(line)
        if len(questions) >= limit:
            break
    return questions


# ---------------------------------------------------------------------------
# auth / account
# ---------------------------------------------------------------------------


@mcp.tool(
    name="notebooklm_auth_status",
    annotations={
        "title": "Check NotebookLM Auth Status",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)
async def notebooklm_auth_status() -> str:
    """Check whether a valid NotebookLM session exists.

    Verifies that stored Google session cookies (written by `notebooklm login`)
    exist and still work by making a lightweight API call. Run this first if
    other tools return authentication errors.

    Returns:
        str: Markdown status report — either "authenticated" with the active
        profile and notebook count, or instructions for the user to log in.
    """
    storage = nlm_paths.get_storage_path(profile=profile())
    if not Path(storage).exists():
        return f"Not logged in — no stored session found at `{storage}`.\n\n{LOGIN_HINT}"
    try:
        client = await get_client()
        notebooks = await client.notebooks.list()
    except Exception as e:
        await reset_client()
        if isinstance(e, AuthError):
            return f"Stored session found but expired or invalid.\n\n{LOGIN_HINT}"
        return format_error(e)
    prof = profile() or "default"
    return (
        f"Authenticated (profile: `{prof}`). "
        f"Account has {len(notebooks)} notebook(s). Session storage: `{storage}`."
    )


async def _enumerate_browser_google_accounts(browser: str) -> list[Any] | str:
    """Read Google accounts signed in to a local browser. Returns accounts or an error string."""
    from notebooklm import auth as nlm_auth
    from notebooklm.cli.services.login import _read_browser_cookies

    raw = await asyncio.to_thread(_read_browser_cookies, browser, verbose=False)
    if not isinstance(raw, list):
        return (
            f"Could not read cookies from {browser} ({type(raw).__name__}). "
            "The browser may not be installed or has no Google session. Try another "
            "browser, or use notebooklm_login with method='interactive'."
        )
    storage_state = nlm_auth.convert_rookiepy_cookies_to_storage_state(raw)
    jar = nlm_auth.build_cookie_jar(cookies=nlm_auth.extract_cookies_with_domains(storage_state))
    return await nlm_auth.enumerate_accounts(jar)


@mcp.tool(
    name="notebooklm_list_google_accounts",
    annotations={
        "title": "List Google Accounts in Browser",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)
async def notebooklm_list_google_accounts(
    browser: Annotated[
        str,
        Field(description="Browser to inspect: chrome, brave, edge, arc, firefox, safari, or 'auto'"),
    ] = "chrome",
) -> str:
    """List the Google accounts currently signed in to the user's browser.

    Call this BEFORE notebooklm_login when connecting for the first time (or
    reconnecting): if more than one account is found, show the user the list
    and ask which account to connect, then call notebooklm_login with that
    email as `account`. Reads cookies locally; nothing is stored yet.

    Returns:
        str: Markdown list of signed-in accounts (email, browser profile,
        whether it's the browser's default), or an error with next steps.
    """
    try:
        accounts = await _enumerate_browser_google_accounts(browser)
        if isinstance(accounts, str):
            return accounts
    except Exception as e:
        return format_error(e)

    if not accounts:
        return (
            f"No signed-in Google accounts found in {browser}. The user should sign in to "
            "Google in that browser first, or use notebooklm_login with method='interactive'."
        )
    lines = [f"# Google accounts signed in to {browser} ({len(accounts)})", ""]
    for a in accounts:
        default = " — browser default" if a.is_default else ""
        prof = f" (browser profile: {a.browser_profile})" if a.browser_profile else ""
        lines.append(f"- **{a.email}**{prof}{default}")
    lines += ["", "Ask the user which account to connect, then call notebooklm_login with that email as `account`."]
    return "\n".join(lines)


@mcp.tool(
    name="notebooklm_login",
    annotations={
        "title": "Log in to NotebookLM",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
    },
)
async def notebooklm_login(
    method: Annotated[
        Literal["browser_cookies", "interactive"],
        Field(
            description="'browser_cookies' (default, no interaction): reads the Google session "
            "from a browser the user is already signed into. 'interactive': opens a browser "
            "window for the user to sign in manually — use as fallback"
        ),
    ] = "browser_cookies",
    browser: Annotated[
        str,
        Field(
            description="Which browser. For browser_cookies: chrome, brave, edge, arc, firefox, safari "
            "(optionally with profile, e.g. 'chrome::Profile 1'). For interactive: chrome, chromium, or msedge"
        ),
    ] = "chrome",
    account: Annotated[
        str | None,
        Field(description="Google account email to select when several are signed in (browser_cookies only)"),
    ] = None,
    ctx: Context = None,
) -> str:
    """Authenticate with NotebookLM using the user's Google account.

    Just call it: when several Google accounts are signed in to the browser
    and no `account` is given, a native account-picker dialog is shown to the
    user automatically (on clients that support elicitation; otherwise the
    tool returns the account list so you can ask the user in chat).

    Default method reads session cookies directly from an installed browser
    where the user is already signed in to Google — no password, no typing.
    On macOS this may trigger a one-time system Keychain permission prompt the
    user must approve. If it fails (browser not signed in, permission denied),
    retry with method='interactive', which opens a browser window for a normal
    Google sign-in and captures the session automatically.

    Returns:
        str: Success confirmation with the account's notebook count, or the
        login error with concrete next steps.
    """
    # Multiple accounts and none chosen? Pop a native account-picker dialog.
    if method == "browser_cookies" and not account:
        try:
            accounts = await _enumerate_browser_google_accounts(browser)
        except Exception:
            accounts = []  # fall through to default-account login
        if isinstance(accounts, list) and len(accounts) > 1:
            emails = [a.email for a in accounts]
            listing = "\n".join(f"- {e}" for e in emails)
            try:
                schema: type[BaseModel] = create_model(
                    "GoogleAccountChoice",
                    account=(
                        Literal[tuple(emails)],
                        Field(description="Google account to connect to NotebookLM"),
                    ),
                )
                result = await ctx.elicit(
                    message="Which Google account do you want to connect to NotebookLM?",
                    schema=schema,
                )
                if result.action != "accept":
                    return "Login cancelled — the user dismissed the account picker."
                account = result.data.account
            except Exception:
                # Client doesn't support elicitation dialogs — ask via chat instead.
                return (
                    f"Multiple Google accounts are signed in to {browser}:\n{listing}\n\n"
                    "Ask the user which one to connect, then call notebooklm_login again "
                    "with that email as `account`."
                )

    cmd = [sys.executable, "-m", "notebooklm", "login"]
    if method == "browser_cookies":
        cmd += ["--browser-cookies", browser]
        if account:
            cmd += ["--account", account]
        timeout = 180
    else:
        import importlib.util

        if importlib.util.find_spec("playwright") is None:
            return (
                "Error: the interactive sign-in window needs the optional Playwright dependency, "
                "which is not installed (it is skipped by default to keep installation fast). "
                "Two options:\n"
                "1. Preferred: use method='browser_cookies' instead — have the user sign in to Google "
                "in Chrome (or another browser) once, then log in from there with no extra installs.\n"
                "2. Or install the fallback: run `uv sync --extra interactive-login && uv run playwright "
                "install chromium` in the connector directory, then retry."
            )
        if browser not in ("chrome", "chromium", "msedge"):
            browser = "chrome"
        cmd += ["--browser", browser]
        timeout = 600  # user has to type their password in the opened window
    if profile():
        cmd += ["--storage", str(nlm_paths.get_storage_path(profile=profile()))]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL,
        )
        out_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = out_bytes.decode(errors="replace").strip()
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return (
            f"Error: login timed out after {timeout}s. "
            "If a browser window or a macOS Keychain prompt is open, ask the user to complete it, "
            "then run notebooklm_auth_status to check."
        )
    except Exception as e:
        return format_error(e)

    tail = "\n".join(output.splitlines()[-15:])
    if proc.returncode != 0:
        hints = []
        if method == "browser_cookies":
            hints.append(
                "Common causes: the browser has no signed-in Google session, or (macOS) Keychain "
                "access was denied. Try again, try another browser (brave/edge/arc/firefox/safari), "
                "or retry with method='interactive' to sign in via a browser window."
            )
        else:
            hints.append("The user may have closed the window before login completed.")
        return f"Login failed (exit {proc.returncode}).\n```\n{tail}\n```\n" + " ".join(hints)

    # Fresh cookies on disk — rebuild the client and verify they work.
    await reset_client()
    try:
        client = await get_client()
        notebooks = await client.notebooks.list()
    except Exception as e:
        return f"Login command succeeded but verification failed: {format_error(e)}\nCLI output:\n```\n{tail}\n```"
    return f"Logged in successfully. The account has {len(notebooks)} notebook(s). Sessions last ~2-4 weeks."


# ---------------------------------------------------------------------------
# notebooks
# ---------------------------------------------------------------------------


@mcp.tool(
    name="notebooklm_list_notebooks",
    annotations={
        "title": "List NotebookLM Notebooks",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)
async def notebooklm_list_notebooks() -> str:
    """List all notebooks in the user's NotebookLM account.

    Returns:
        str: Markdown list, one line per notebook:
        title, notebook ID (needed by every other tool), source count, creation date.
    """
    try:
        client = await get_client()
        notebooks = await client.notebooks.list()
    except Exception as e:
        return format_error(e)
    if not notebooks:
        return "No notebooks found. Create one with notebooklm_create_notebook."
    lines = [f"# Notebooks ({len(notebooks)})", ""]
    lines += [_fmt_notebook_line(nb) for nb in notebooks]
    return "\n".join(lines)


@mcp.tool(
    name="notebooklm_create_notebook",
    annotations={
        "title": "Create NotebookLM Notebook",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
    },
)
async def notebooklm_create_notebook(
    title: Annotated[str, Field(description="Title for the new notebook", min_length=1, max_length=200)],
) -> str:
    """Create a new, empty NotebookLM notebook.

    After creating, add sources with notebooklm_add_source before asking
    questions or generating content.

    Returns:
        str: Confirmation with the new notebook's ID.
    """
    try:
        client = await get_client()
        nb = await client.notebooks.create(title)
    except Exception as e:
        return format_error(e)
    return f"Created notebook **{nb.title}** with ID `{nb.id}`. Add sources next with notebooklm_add_source."


@mcp.tool(
    name="notebooklm_get_notebook",
    annotations={
        "title": "Get NotebookLM Notebook Overview",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)
async def notebooklm_get_notebook(
    notebook_id: Annotated[str, Field(description="Notebook ID (from notebooklm_list_notebooks)")],
    include_summary: Annotated[
        bool,
        Field(description="Also fetch NotebookLM's AI-generated summary of the notebook (slower)"),
    ] = True,
) -> str:
    """Get a notebook's overview: title, sources with IDs and status, and optionally its AI summary.

    Use this to find source IDs (for scoping questions or generation to
    specific sources) and to check whether newly added sources are ready.

    Returns:
        str: Markdown overview — notebook title/ID, AI summary (if requested),
        and one line per source with title, source ID, processing status, and URL.
    """
    try:
        client = await get_client()
        nb = await client.notebooks.get(notebook_id)
        sources = await client.sources.list(notebook_id)
        summary = ""
        if include_summary:
            try:
                summary = await client.notebooks.get_summary(notebook_id)
            except Exception:
                summary = ""
    except Exception as e:
        return format_error(e)

    lines = [f"# {nb.title} (`{nb.id}`)", ""]
    if summary:
        lines += ["## Summary", summary.strip(), ""]
    lines.append(f"## Sources ({len(sources)})")
    if sources:
        lines += [_fmt_source_line(s) for s in sources]
    else:
        lines.append("_No sources yet — add some with notebooklm_add_source._")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------


@mcp.tool(
    name="notebooklm_add_source",
    annotations={
        "title": "Add Source to Notebook",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
    },
)
async def notebooklm_add_source(
    notebook_id: Annotated[str, Field(description="Notebook ID to add the source to")],
    kind: Annotated[
        Literal["url", "text", "file"],
        Field(description="Source kind: 'url' (webpage/YouTube/PDF link), 'text' (pasted text), 'file' (local file path)"),
    ],
    content: Annotated[
        str,
        Field(description="The URL, the raw text content, or the absolute local file path, depending on kind"),
    ],
    title: Annotated[
        str | None,
        Field(description="Source title. Required for kind='text'; optional for 'file'; ignored for 'url'"),
    ] = None,
    wait: Annotated[
        bool,
        Field(description="Wait until NotebookLM finishes processing the source (up to ~2 min). Set false to return immediately"),
    ] = True,
) -> str:
    """Add a source document to a notebook.

    Supports web URLs (articles, PDFs, YouTube videos), pasted text, and local
    files (PDF, txt, markdown, audio, and most document formats). NotebookLM
    processes sources asynchronously; with wait=true this returns once the
    source is ready to be queried.

    Returns:
        str: Confirmation with the new source's ID and processing status,
        or an actionable error (e.g. unsupported/paywalled content).
    """
    if kind == "text" and not title:
        return "Error: title is required when kind='text'."
    if kind == "file" and not Path(content).expanduser().is_file():
        return f"Error: file not found: {content}"
    try:
        client = await get_client()
        if kind == "url":
            src = await client.sources.add_url(notebook_id, content, wait=wait)
        elif kind == "text":
            src = await client.sources.add_text(notebook_id, title or "Untitled", content, wait=wait)
        else:
            src = await client.sources.add_file(
                notebook_id, str(Path(content).expanduser()), wait=wait, title=title
            )
    except Exception as e:
        return format_error(e)
    status = getattr(src.status, "name", str(src.status)).lower()
    note = "" if wait else " Processing continues in the background — check with notebooklm_get_notebook."
    return f"Added source **{src.title or content}** (`{src.id}`), status: {status}.{note}"


@mcp.tool(
    name="notebooklm_ask",
    annotations={
        "title": "Ask NotebookLM a Question",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)
async def notebooklm_ask(
    notebook_id: Annotated[str, Field(description="Notebook ID to query")],
    question: Annotated[str, Field(description="The question to ask about the notebook's sources", min_length=1)],
    source_ids: Annotated[
        list[str] | None,
        Field(description="Restrict the answer to these source IDs (default: all sources in the notebook)"),
    ] = None,
    conversation_id: Annotated[
        str | None,
        Field(description="Pass the conversation_id from a previous answer to ask a follow-up in the same conversation"),
    ] = None,
    thorough: Annotated[
        bool | None,
        Field(description="Auto-coverage mode: after the first answer, have NotebookLM find gaps and auto-ask follow-ups, then return a combined, more complete answer. Slower and uses several extra queries from the daily quota. Use when the user wants a thorough/deep/complete answer. Default off (set by NOTEBOOKLM_THOROUGH env var)"),
    ] = None,
    max_followups: Annotated[
        int,
        Field(description="In thorough mode, the maximum number of auto follow-up questions (each costs one query)", ge=1, le=5),
    ] = DEFAULT_MAX_FOLLOWUPS,
) -> str:
    """Ask a question and get an answer grounded exclusively in the notebook's sources.

    This is NotebookLM's core capability: answers cite the underlying source
    passages and do not draw on outside knowledge, making them reliable for
    research over the user's own documents. Counts against the account's daily
    chat quota (~50/day on free accounts).

    With thorough=true, runs auto-coverage: after the first answer it asks
    NotebookLM which aspects of the question were not fully covered, then
    automatically asks those follow-ups (up to max_followups) in the same
    conversation and returns one merged answer. This gives more complete
    results at the cost of extra quota and latency — prefer it only when the
    user explicitly wants a deep/thorough answer.

    Returns:
        str: Markdown with the answer (or merged answer in thorough mode), a
        conversation_id for follow-up questions, and a Citations section
        mapping each cited source (title + source ID) with quoted snippets.
    """
    use_thorough = DEFAULT_THOROUGH if thorough is None else thorough
    try:
        client = await get_client()
        result = await client.chat.ask(
            notebook_id, question, source_ids=source_ids, conversation_id=conversation_id
        )
        titles: dict[str, str] = {}
        try:
            titles = {s.id: (s.title or s.id) for s in await client.sources.list(notebook_id)}
        except Exception:
            titles = {}
    except Exception as e:
        return format_error(e)

    by_source: dict[str, list[str]] = {}
    _collect_citations(result, by_source)

    # Simple (default) path.
    if not use_thorough:
        lines = [result.answer.strip(), "", f"_conversation_id: `{result.conversation_id}` (pass back for follow-ups)_"]
        lines += _render_citations(by_source, titles)
        return "\n".join(lines)

    # Thorough path: detect gaps, auto-ask follow-ups, merge.
    conv = result.conversation_id
    sections = [f"## Answer\n{result.answer.strip()}"]
    followups_done: list[str] = []
    try:
        meta_q = (
            f'Reviewing your previous answer to my question: "{question}". '
            f"List up to {max_followups} specific follow-up questions whose answers are in "
            "the sources but were missing or only partially covered in that answer. "
            "Reply with a plain numbered list of questions only, no preamble. "
            "If the previous answer already fully covered the question, reply with exactly: NONE"
        )
        meta = await client.chat.ask(notebook_id, meta_q, source_ids=source_ids, conversation_id=conv)
        conv = meta.conversation_id
        for fq in _parse_followups(meta.answer, max_followups):
            fr = await client.chat.ask(notebook_id, fq, source_ids=source_ids, conversation_id=conv)
            conv = fr.conversation_id
            _collect_citations(fr, by_source)
            sections.append(f"### {fq}\n{fr.answer.strip()}")
            followups_done.append(fq)
    except Exception:
        # Any failure mid-coverage: keep whatever we have, don't lose the main answer.
        pass

    header = (
        f"_Thorough mode: asked {len(followups_done)} auto follow-up(s) to fill gaps._"
        if followups_done
        else "_Thorough mode: the first answer already covered the question._"
    )
    lines = [header, ""] + ["\n\n".join(sections)]
    lines += ["", f"_conversation_id: `{conv}` (pass back for follow-ups)_"]
    lines += _render_citations(by_source, titles)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# studio generation
# ---------------------------------------------------------------------------

GENERATION_KINDS = Literal[
    "audio", "video", "report", "quiz", "flashcards", "mind_map",
    "infographic", "slide_deck", "data_table",
]


@mcp.tool(
    name="notebooklm_generate",
    annotations={
        "title": "Generate NotebookLM Studio Content",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
    },
)
async def notebooklm_generate(
    notebook_id: Annotated[str, Field(description="Notebook ID to generate from")],
    kind: Annotated[
        GENERATION_KINDS,
        Field(description="What to generate: 'audio' (podcast-style Audio Overview), 'video', 'report', 'quiz', 'flashcards', 'mind_map', 'infographic', 'slide_deck', or 'data_table'"),
    ],
    instructions: Annotated[
        str | None,
        Field(description="Optional steering instructions (topic focus, tone, audience). For kind='report' with report_format='custom' this is the report prompt"),
    ] = None,
    source_ids: Annotated[
        list[str] | None,
        Field(description="Generate from these source IDs only (default: all sources)"),
    ] = None,
    report_format: Annotated[
        Literal["briefing_doc", "study_guide", "blog_post", "custom"],
        Field(description="Only for kind='report': which report type to generate"),
    ] = "briefing_doc",
    language: Annotated[
        str,
        Field(description="Output language code, e.g. 'en'"),
    ] = "en",
) -> str:
    """Start generating Studio content (audio overview, report, quiz, etc.) from a notebook's sources.

    Generation runs asynchronously inside NotebookLM and can take 1-10 minutes
    (audio/video are slowest). This tool starts the job and returns a task_id —
    poll with notebooklm_generation_status, then fetch the result with
    notebooklm_download_artifact. Exception: mind_map completes immediately.

    Returns:
        str: Markdown with the task_id and current status, plus polling
        instructions; or the finished mind map confirmation.
    """
    try:
        client = await get_client()
        a = client.artifacts
        if kind == "mind_map":
            result = await a.generate_mind_map(
                notebook_id, source_ids=source_ids, language=language, instructions=instructions
            )
            return (
                "Mind map generated. Download it with notebooklm_download_artifact "
                "(kind='mind_map') or view it in the NotebookLM UI."
            )
        if kind == "audio":
            status = await a.generate_audio(notebook_id, source_ids=source_ids, language=language, instructions=instructions)
        elif kind == "video":
            status = await a.generate_video(notebook_id, source_ids=source_ids, language=language, instructions=instructions)
        elif kind == "quiz":
            status = await a.generate_quiz(notebook_id, source_ids=source_ids, instructions=instructions)
        elif kind == "flashcards":
            status = await a.generate_flashcards(notebook_id, source_ids=source_ids, instructions=instructions)
        elif kind == "infographic":
            status = await a.generate_infographic(notebook_id, source_ids=source_ids, language=language, instructions=instructions)
        elif kind == "slide_deck":
            status = await a.generate_slide_deck(notebook_id, source_ids=source_ids, language=language, instructions=instructions)
        elif kind == "data_table":
            status = await a.generate_data_table(notebook_id, source_ids=source_ids, language=language, instructions=instructions)
        else:  # report
            status = await a.generate_report(
                notebook_id,
                report_format=ReportFormat(report_format),
                source_ids=source_ids,
                language=language,
                custom_prompt=instructions if report_format == "custom" else None,
            )
    except Exception as e:
        return format_error(e)
    return (
        f"Started {kind} generation.\n{_fmt_generation(status)}\n\n"
        "Poll with notebooklm_generation_status (audio/video typically take several "
        "minutes), then download with notebooklm_download_artifact."
    )


@mcp.tool(
    name="notebooklm_generation_status",
    annotations={
        "title": "Check Generation Status",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)
async def notebooklm_generation_status(
    notebook_id: Annotated[str, Field(description="Notebook ID the generation was started in")],
    task_id: Annotated[str, Field(description="task_id returned by notebooklm_generate")],
) -> str:
    """Check whether a Studio generation task has finished.

    Returns:
        str: Markdown with task status ('completed', 'in_progress', or
        'failed' with the error). Once completed, use
        notebooklm_download_artifact to retrieve the output.
    """
    try:
        client = await get_client()
        status = await client.artifacts.poll_status(notebook_id, task_id)
    except Exception as e:
        return format_error(e)
    return _fmt_generation(status)


@mcp.tool(
    name="notebooklm_list_artifacts",
    annotations={
        "title": "List Studio Artifacts",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)
async def notebooklm_list_artifacts(
    notebook_id: Annotated[str, Field(description="Notebook ID")],
    artifact_type: Annotated[
        Literal["audio", "video", "report", "quiz", "flashcards", "mind_map", "infographic", "slide_deck", "data_table"] | None,
        Field(description="Filter to one artifact type (default: all)"),
    ] = None,
) -> str:
    """List generated Studio artifacts (audio overviews, reports, quizzes, ...) in a notebook.

    Returns:
        str: Markdown list with each artifact's title, ID, kind, status
        (completed/processing/failed), and creation date.
    """
    try:
        client = await get_client()
        artifacts = await client.artifacts.list(
            notebook_id, ArtifactType(artifact_type) if artifact_type else None
        )
    except Exception as e:
        return format_error(e)
    if not artifacts:
        return "No artifacts found. Generate some with notebooklm_generate."
    lines = [f"# Artifacts ({len(artifacts)})", ""]
    for art in artifacts:
        kind = getattr(art.kind, "value", art.kind)
        lines.append(
            f"- **{art.title}** (`{art.id}`) — {kind}, {art.status_str}, created {_fmt_dt(art.created_at)}"
        )
    return "\n".join(lines)


_DOWNLOADERS = {
    "audio": ("download_audio", ".mp3"),
    "video": ("download_video", ".mp4"),
    "report": ("download_report", ".md"),
    "quiz": ("download_quiz", ".json"),
    "flashcards": ("download_flashcards", ".json"),
    "mind_map": ("download_mind_map", ".json"),
    "infographic": ("download_infographic", ".png"),
    "slide_deck": ("download_slide_deck", ".pdf"),
    "data_table": ("download_data_table", ".csv"),
}


@mcp.tool(
    name="notebooklm_download_artifact",
    annotations={
        "title": "Download Studio Artifact",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)
async def notebooklm_download_artifact(
    notebook_id: Annotated[str, Field(description="Notebook ID")],
    kind: Annotated[
        Literal["audio", "video", "report", "quiz", "flashcards", "mind_map", "infographic", "slide_deck", "data_table"],
        Field(description="Artifact kind — determines file format (audio→mp3, report→md, slide_deck→pdf, quiz/flashcards/mind_map→json, infographic→png, data_table→csv)"),
    ],
    output_path: Annotated[str, Field(description="Absolute local path to save the file to, including extension")],
    artifact_id: Annotated[
        str | None,
        Field(description="Specific artifact ID (from notebooklm_list_artifacts). Default: the most recent artifact of that kind"),
    ] = None,
) -> str:
    """Download a completed Studio artifact to a local file.

    Returns:
        str: The saved file path, or an error if the artifact is still
        processing or does not exist.
    """
    method_name, _ = _DOWNLOADERS[kind]
    out = Path(output_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        client = await get_client()
        saved = await getattr(client.artifacts, method_name)(notebook_id, str(out), artifact_id)
    except Exception as e:
        return format_error(e)
    return f"Saved {kind} to `{saved}`."


# ---------------------------------------------------------------------------
# deletion
# ---------------------------------------------------------------------------


@mcp.tool(
    name="notebooklm_delete",
    annotations={
        "title": "Delete Notebook / Source / Artifact",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def notebooklm_delete(
    notebook_id: Annotated[str, Field(description="Notebook ID")],
    target: Annotated[
        Literal["notebook", "source", "artifact"],
        Field(description="What to delete: the whole notebook, one source, or one artifact"),
    ],
    target_id: Annotated[
        str | None,
        Field(description="Source or artifact ID to delete. Not needed when target='notebook'"),
    ] = None,
) -> str:
    """Permanently delete a notebook, a source, or a generated artifact.

    This cannot be undone. Deleting a notebook removes all its sources,
    chat history, and artifacts.

    Returns:
        str: Confirmation of what was deleted.
    """
    if target != "notebook" and not target_id:
        return f"Error: target_id is required when target='{target}'."
    try:
        client = await get_client()
        if target == "notebook":
            await client.notebooks.delete(notebook_id)
            return f"Deleted notebook `{notebook_id}` and all its contents."
        if target == "source":
            await client.sources.delete(notebook_id, target_id)
            return f"Deleted source `{target_id}` from notebook `{notebook_id}`."
        await client.artifacts.delete(notebook_id, target_id)
        return f"Deleted artifact `{target_id}` from notebook `{notebook_id}`."
    except Exception as e:
        return format_error(e)


def main() -> None:
    """Entry point: run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
