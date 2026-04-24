from __future__ import annotations

import json
import logging
import time

import aiohttp
import requests

from src.infrastructure.identity import credential

logger = logging.getLogger(__name__)

#_FABRIC_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
_FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
_TOKEN_REFRESH_BUFFER_SECS = 300


class FabricRpcClient:
    """
    Client that talks to a Microsoft Fabric Data Agent via JSON-RPC over HTTP.

    The Fabric endpoint returns **Server-Sent Events** (SSE).  Each ``data:``
    frame is a JSON-RPC response; we iterate over them and return the first
    frame that contains a non-empty result.

    Both sync (``ask``) and async (``ask_async``) entry-points are provided so
    callers can pick whichever fits their runtime.

    Usage::

        client = FabricRpcClient(server_url, tool_name="my_tool")
        # sync
        answer = client.ask("How many loads were delivered last week?")
        # async
        answer = await client.ask_async("How many loads were delivered last week?")
    """

    def __init__(self, server_url: str, tool_name: str) -> None:
        if not server_url:
            raise ValueError("server_url is required")
        if not tool_name:
            raise ValueError("tool_name is required")
        self._server_url = server_url.rstrip("/")
        self._tool_name = tool_name
        self._token = credential.get_token(_FABRIC_SCOPE)

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _refresh_token_if_needed(self) -> None:
        if time.time() >= self._token.expires_on - _TOKEN_REFRESH_BUFFER_SECS:
            self._token = credential.get_token(_FABRIC_SCOPE)

    def _auth_headers(self) -> dict[str, str]:
        self._refresh_token_if_needed()
        return {
            "Authorization": f"Bearer {self._token.token}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, question: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": self._tool_name,
                "arguments": {"userQuestion": question},
            },
        }

    # ------------------------------------------------------------------
    # Public API — synchronous (uses requests)
    # ------------------------------------------------------------------

    def ask(self, question: str, *, timeout: int = 120) -> str:
        """Send a question synchronously and return the agent's text answer.

        The Fabric endpoint streams SSE; we parse every ``data:`` frame and
        return the first one that carries a non-empty result.
        """
        if not question.strip():
            raise ValueError("question cannot be empty")

        payload = self._build_payload(question)
        logger.info("Fabric RPC request → %s", self._server_url)

        response = requests.post(
            self._server_url,
            headers=self._auth_headers(),
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return self._parse_sse_response(response.text)

    def ask_raw(self, question: str, *, timeout: int = 120) -> str:
        """Send a question synchronously and return the raw response text."""
        if not question.strip():
            raise ValueError("question cannot be empty")

        response = requests.post(
            self._server_url,
            headers=self._auth_headers(),
            json=self._build_payload(question),
            timeout=timeout,
        )
        response.raise_for_status()
        return response.text

    # ------------------------------------------------------------------
    # Public API — asynchronous (uses aiohttp)
    # ------------------------------------------------------------------

    async def ask_async(self, question: str, *, timeout: int = 120) -> str:
        """Send a question asynchronously and return the agent's text answer."""
        if not question.strip():
            raise ValueError("question cannot be empty")

        payload = self._build_payload(question)
        logger.info("Fabric RPC async request → %s", self._server_url)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self._server_url,
                headers=self._auth_headers(),
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                response.raise_for_status()
                text = await response.text()

        return self._parse_sse_response(text)

    async def ask_raw_async(self, question: str, *, timeout: int = 120) -> str:
        """Send a question asynchronously and return the raw response text."""
        if not question.strip():
            raise ValueError("question cannot be empty")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self._server_url,
                headers=self._auth_headers(),
                json=self._build_payload(question),
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                response.raise_for_status()
                return await response.text()

    # ------------------------------------------------------------------
    # SSE / JSON-RPC parsing helpers
    # ------------------------------------------------------------------

    @classmethod
    def _parse_sse_response(cls, raw_text: str) -> str:
        """Parse an SSE stream and extract the first meaningful result."""
        for line in raw_text.split("\n"):
            if not line.startswith("data: "):
                continue
            try:
                parsed = json.loads(line[6:])
            except json.JSONDecodeError:
                continue

            # JSON-RPC error
            if "error" in parsed:
                err = parsed["error"]
                code = err.get("code", "unknown")
                message = err.get("message", "Unknown JSON-RPC error")
                return f"JSON-RPC error {code}: {message}"

            result = parsed.get("result", {})
            text = cls._extract_text(result)
            if text:
                return text

        # Fallback: maybe the response is plain JSON (non-SSE)
        try:
            body = json.loads(raw_text)
            if "error" in body:
                err = body["error"]
                return f"JSON-RPC error {err.get('code', '?')}: {err.get('message', '')}"
            result = body.get("result", {})
            text = cls._extract_text(result)
            if text:
                return text
        except json.JSONDecodeError:
            pass

        return raw_text or "No response received from the Fabric Data Agent."

    @staticmethod
    def _extract_text(result: dict | list | str | None) -> str:
        """Best-effort extraction of a text answer from a JSON-RPC result."""
        if not result:
            return ""
        if isinstance(result, str):
            return result

        if isinstance(result, dict):
            # MCP-style: result.content[].text
            content = result.get("content")
            if isinstance(content, list) and content:
                first = content[0]
                if isinstance(first, dict):
                    return first.get("text", str(first))
                return str(first)

            # Fallback keys
            for key in ("text", "answer", "message", "data"):
                if key in result and result[key]:
                    return str(result[key])

        return str(result)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_fabric_rpc_client: FabricRpcClient | None = None


def get_fabric_rpc_client(server_url: str, tool_name: str) -> FabricRpcClient:
    """Return the process-level FabricRpcClient, creating it on first call."""
    global _fabric_rpc_client
    if _fabric_rpc_client is None:
        _fabric_rpc_client = FabricRpcClient(server_url, tool_name)
    return _fabric_rpc_client  # type: ignore[return-value]

