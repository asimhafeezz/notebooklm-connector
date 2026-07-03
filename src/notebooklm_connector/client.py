"""Shared NotebookLM client lifecycle and error handling.

A single NotebookLMClient is created lazily on first tool call and reused for
the lifetime of the MCP server process. Auth tokens come from the storage
written by `notebooklm login` (the notebooklm-py CLI bundled with this project).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from notebooklm import (
    AuthError,
    ConfigurationError,
    NotebookLMClient,
    NotFoundError,
    RateLimitError,
    RPCError,
    SourceProcessingError,
    WaitTimeoutError,
)

_client: NotebookLMClient | None = None
_client_cm: Any = None
_lock = asyncio.Lock()

LOGIN_HINT = (
    "No valid NotebookLM session. To connect: call notebooklm_list_google_accounts to see "
    "which Google accounts are signed in to the user's browser, ask the user which one to "
    "use, then call notebooklm_login with that email as `account`. No password is needed — "
    "the session is read from the browser. Sessions last roughly 2-4 weeks."
)


def profile() -> str | None:
    """Named auth profile, for people with multiple Google accounts."""
    return os.environ.get("NOTEBOOKLM_PROFILE") or None


async def get_client() -> NotebookLMClient:
    """Return the shared client, creating it from stored auth on first use."""
    global _client, _client_cm
    async with _lock:
        if _client is None:
            cm = NotebookLMClient.from_storage(profile=profile())
            _client = await cm.__aenter__()
            _client_cm = cm
        return _client


async def reset_client() -> None:
    """Drop the shared client so the next call re-reads stored auth."""
    global _client, _client_cm
    async with _lock:
        if _client_cm is not None:
            try:
                await _client_cm.__aexit__(None, None, None)
            except Exception:
                pass
        _client = None
        _client_cm = None


def format_error(e: Exception) -> str:
    """Map notebooklm-py exceptions to actionable messages for the agent."""
    if isinstance(e, (AuthError, ConfigurationError)) or isinstance(e, FileNotFoundError):
        return f"Error: authentication problem ({type(e).__name__}). {LOGIN_HINT}"
    if isinstance(e, RateLimitError):
        return (
            "Error: NotebookLM rate limit hit. Free accounts allow roughly 50 "
            "chat queries per day. Wait before retrying, or continue tomorrow."
        )
    if isinstance(e, NotFoundError):
        return (
            f"Error: not found ({e}). Check the notebook/source/artifact ID — "
            "use notebooklm_list_notebooks or notebooklm_get_notebook to look up valid IDs."
        )
    if isinstance(e, SourceProcessingError):
        return (
            f"Error: NotebookLM failed to process the source ({e}). The document may be "
            "unsupported, paywalled, or too large. Try a different URL or upload the file directly."
        )
    if isinstance(e, WaitTimeoutError):
        return (
            f"Error: timed out waiting ({e}). The operation is likely still running inside "
            "NotebookLM — check again shortly (sources: notebooklm_get_notebook; "
            "generations: notebooklm_generation_status)."
        )
    if isinstance(e, RPCError):
        return (
            f"Error: NotebookLM internal API call failed ({type(e).__name__}: {e}). "
            "This connector relies on undocumented Google APIs; if this persists, "
            "the API may have changed — try `uv sync --upgrade` to update notebooklm-py."
        )
    return f"Error: {type(e).__name__}: {e}"
