from __future__ import annotations

import asyncio
import time
import uuid
import warnings

import aiohttp
from openai import AsyncOpenAI

from src.infrastructure.identity import credential

# Suppress OpenAI Assistants API deprecation warnings —
# Fabric Data Agents don't support the newer Responses API yet.
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r".*Assistants API is deprecated.*",
)

_FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
# Rebuild the OpenAI client this many seconds before the token actually expires.
_TOKEN_REFRESH_BUFFER_SECS = 300


def _normalize_base_url(data_agent_url: str) -> str:
    """Derive the private base URL used for Fabric-specific thread operations."""
    url = data_agent_url
    if "aiskills" in url:
        url = url.replace("aiskills", "dataagents")
    return url.removesuffix("/openai").replace("/aiassistant", "/__private/aiassistant")


class FabricDataAgentClient:
    """
    Async client for Microsoft Fabric Data Agents using DefaultAzureCredential.

    Handles token lifecycle: a single token is reused for all calls and
    automatically refreshed when it is within _TOKEN_REFRESH_BUFFER_SECS of
    expiry — matching the pattern in the reference client but without
    interactive browser authentication.

    Usage::

        client = FabricDataAgentClient(data_agent_url)
        answer = await client.ask("How many loads were delivered last week?")
    """

    def __init__(self, data_agent_url: str) -> None:
        if not data_agent_url:
            raise ValueError("data_agent_url is required")
        self._data_agent_url = data_agent_url
        self._token = credential.get_token(_FABRIC_SCOPE)
        self._assistant_id: str | None = None
        self._openai_client: AsyncOpenAI | None = None

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _refresh_token_if_needed(self) -> None:
        """Refresh the cached token when it is close to expiry."""
        if time.time() >= self._token.expires_on - _TOKEN_REFRESH_BUFFER_SECS:
            self._token = credential.get_token(_FABRIC_SCOPE)

    def _auth_headers(self) -> dict[str, str]:
        self._refresh_token_if_needed()
        return {
            "Authorization": f"Bearer {self._token.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "ActivityId": str(uuid.uuid4()),
        }

    # ------------------------------------------------------------------
    # OpenAI client
    # ------------------------------------------------------------------

    def _build_openai_client(self) -> AsyncOpenAI:
        """Return a cached AsyncOpenAI client, rebuilding only when the token refreshes."""
        old_token = self._token.token
        self._refresh_token_if_needed()
        if self._openai_client is None or self._token.token != old_token:
            self._openai_client = AsyncOpenAI(
                api_key="",  # not used — Fabric authenticates via Bearer token
                base_url=self._data_agent_url,
                default_query={"api-version": "2024-05-01-preview"},
                default_headers=self._auth_headers(),
            )
        return self._openai_client

    # ------------------------------------------------------------------
    # Thread management (Fabric-specific, not part of OpenAI spec)
    # ------------------------------------------------------------------

    async def _get_or_create_thread(self, thread_name: str) -> dict:
        """
        Get or create a Fabric conversation thread by name.

        A unique name creates a new thread; reusing a name retrieves the
        existing one, enabling multi-turn conversations.
        """
        base_url = _normalize_base_url(self._data_agent_url)
        url = f'{base_url}/threads/fabric?tag="{thread_name}"'
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=self._auth_headers(),
                timeout=aiohttp.ClientTimeout(total=300),
            ) as response:
                response.raise_for_status()
                thread = await response.json(content_type=None)
        thread["name"] = thread_name
        return thread

    # ------------------------------------------------------------------
    # Assistant ID (created once and reused)
    # ------------------------------------------------------------------

    async def _get_assistant_id(self, client: AsyncOpenAI) -> str:
        if self._assistant_id is None:
            assistant = await client.beta.assistants.create(model="not used")
            self._assistant_id = assistant.id
        return self._assistant_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ask(
        self,
        question: str,
        *,
        thread_name: str | None = None,
        timeout: int = 120,
    ) -> str:
        """
        Ask the Fabric Data Agent a natural language question.

        Args:
            question:    The question to ask.
            thread_name: Reuse a named thread for multi-turn conversations.
                         Pass ``None`` (default) to use a fresh thread.
            timeout:     Seconds to wait for the run to complete.

        Returns:
            The agent's text response.
        """
        if not question.strip():
            raise ValueError("question cannot be empty")

        effective_thread_name = thread_name or f"trucking-{uuid.uuid4()}"
        client = self._build_openai_client()
        assistant_id = await self._get_assistant_id(client)
        thread = await self._get_or_create_thread(effective_thread_name)

        await client.beta.threads.messages.create(
            thread_id=thread["id"],
            role="user",
            content=question,
        )

        run = await client.beta.threads.runs.create(
            thread_id=thread["id"],
            assistant_id=assistant_id,
        )

        deadline = time.time() + timeout
        poll_interval = 0.5
        while run.status in ("queued", "in_progress"):
            if time.time() > deadline:
                return "Request to Fabric Data Agent timed out."
            await asyncio.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.5, 2.0)
            run = await client.beta.threads.runs.retrieve(
                thread_id=thread["id"],
                run_id=run.id,
            )

        messages = await client.beta.threads.messages.list(
            thread_id=thread["id"],
            order="asc",
        )

        responses: list[str] = []
        for msg in messages.data:
            if msg.role == "assistant":
                try:
                    content = msg.content[0]
                    if hasattr(content, "text"):
                        text = getattr(content, "text", None)
                        responses.append(
                            text.value if hasattr(text, "value") else str(text)
                        )
                    else:
                        responses.append(str(content))
                except (IndexError, AttributeError):
                    responses.append(str(msg.content))

        # Clean up the thread (best-effort; errors are non-fatal)
        try:
            await client.beta.threads.delete(thread_id=thread["id"])
        except Exception:
            pass

        return "\n".join(responses) if responses else "No response received from the Fabric Data Agent."

    async def get_run_details(
        self,
        question: str,
        *,
        thread_name: str | None = None,
        timeout: int = 120,
    ) -> dict:
        """
        Ask a question and return detailed run information including steps,
        messages, and any SQL queries generated by the agent.

        Args:
            question:    The question to ask.
            thread_name: Reuse a named thread for multi-turn conversations.
            timeout:     Seconds to wait for the run to complete.

        Returns:
            A dict with keys: question, run_status, run_steps, messages,
            timestamp, and optionally sql_queries / sql_data_previews /
            data_retrieval_query when the agent used a lakehouse data source.
        """
        if not question.strip():
            raise ValueError("question cannot be empty")

        effective_thread_name = thread_name or f"trucking-{uuid.uuid4()}"
        client = self._build_openai_client()
        assistant_id = await self._get_assistant_id(client)
        thread = await self._get_or_create_thread(effective_thread_name)

        await client.beta.threads.messages.create(
            thread_id=thread["id"],
            role="user",
            content=question,
        )

        run = await client.beta.threads.runs.create(
            thread_id=thread["id"],
            assistant_id=assistant_id,
        )

        deadline = time.time() + timeout
        poll_interval = 0.5
        while run.status in ("queued", "in_progress"):
            if time.time() > deadline:
                break
            await asyncio.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.5, 2.0)
            run = await client.beta.threads.runs.retrieve(
                thread_id=thread["id"],
                run_id=run.id,
            )

        steps, messages = await asyncio.gather(
            client.beta.threads.runs.steps.list(thread_id=thread["id"], run_id=run.id),
            client.beta.threads.messages.list(thread_id=thread["id"], order="asc"),
        )

        sql_analysis = self._extract_sql_queries_with_data(steps)

        # Enrich data previews from the final assistant message text when
        # the structured step output didn't yield previews.
        messages_data = messages.model_dump()
        assistant_msgs = [
            m for m in messages_data.get("data", []) if m.get("role") == "assistant"
        ]
        if assistant_msgs:
            raw_content = assistant_msgs[-1].get("content", [])
            text_content = ""
            if raw_content:
                first = raw_content[0]
                if isinstance(first, dict):
                    text_block = first.get("text", "")
                    text_content = (
                        text_block.get("value", "") if isinstance(text_block, dict) else str(text_block)
                    )
                else:
                    text_content = str(first)

            if text_content:
                text_preview = self._extract_data_from_text_response(text_content)
                if text_preview:
                    if not sql_analysis["data_previews"] or not any(sql_analysis["data_previews"]):
                        sql_analysis["data_previews"] = [text_preview]
                    else:
                        sql_analysis["data_previews"].append(text_preview)

        try:
            await client.beta.threads.delete(thread_id=thread["id"])
        except Exception:
            pass

        result: dict = {
            "question": question,
            "run_status": run.status,
            "run_steps": steps.model_dump(),
            "messages": messages_data,
            "timestamp": time.time(),
        }

        if sql_analysis["queries"]:
            result["sql_queries"] = sql_analysis["queries"]
            result["sql_data_previews"] = sql_analysis["data_previews"]
            result["data_retrieval_query"] = sql_analysis["data_retrieval_query"]

        return result

    async def get_raw_run_response(
        self,
        question: str,
        *,
        thread_name: str | None = None,
        timeout: int = 120,
    ) -> dict:
        """
        Ask a question and return the **complete raw** response — every field
        from the run object, all steps, and all messages — without any
        post-processing.

        This is the lowest-level inspection method; use it when you need to
        debug Fabric response structure or build custom parsers on top.

        Args:
            question:    The question to ask.
            thread_name: Reuse a named thread for multi-turn conversations.
            timeout:     Seconds to wait for the run to complete.

        Returns:
            A dict with keys: question, run (full dump), steps (full dump),
            messages (full dump, newest-first), timestamp, timeout, success,
            thread.  On error: question, error, timestamp, success=False.
        """
        if not question.strip():
            raise ValueError("question cannot be empty")

        effective_thread_name = thread_name or f"trucking-{uuid.uuid4()}"

        try:
            client = self._build_openai_client()
            assistant_id = await self._get_assistant_id(client)
            thread = await self._get_or_create_thread(effective_thread_name)

            await client.beta.threads.messages.create(
                thread_id=thread["id"],
                role="user",
                content=question,
            )

            run = await client.beta.threads.runs.create(
                thread_id=thread["id"],
                assistant_id=assistant_id,
            )

            deadline = time.time() + timeout
            poll_interval = 0.5
            while run.status in ("queued", "in_progress"):
                if time.time() > deadline:
                    break
                await asyncio.sleep(poll_interval)
                poll_interval = min(poll_interval * 1.5, 2.0)
                run = await client.beta.threads.runs.retrieve(
                    thread_id=thread["id"],
                    run_id=run.id,
                )

            # Fetch steps and messages concurrently — they are independent calls.
            steps, messages = await asyncio.gather(
                client.beta.threads.runs.steps.list(thread_id=thread["id"], run_id=run.id),
                client.beta.threads.messages.list(thread_id=thread["id"], order="desc"),
            )

            try:
                await client.beta.threads.delete(thread_id=thread["id"])
            except Exception:
                pass

            return {
                "question": question,
                "run": run.model_dump(),
                "steps": steps.model_dump(),
                "messages": messages.model_dump(),
                "timestamp": time.time(),
                "timeout": timeout,
                "success": run.status == "completed",
                "thread": thread,
            }

        except Exception as exc:
            return {
                "question": question,
                "error": str(exc),
                "timestamp": time.time(),
                "success": False,
            }

    # ------------------------------------------------------------------
    # Private helpers — SQL / data extraction from run steps
    # ------------------------------------------------------------------

    def _extract_sql_queries_with_data(self, steps) -> dict:
        """Extract SQL queries and data previews from run steps."""
        import json as _json

        sql_queries: list[str] = []
        data_previews: list[list[str]] = []
        data_retrieval_query: str | None = None
        data_retrieval_query_index: int | None = None

        try:
            for step in steps.data:
                step_details = getattr(step, "step_details", None)
                if not step_details:
                    continue
                for tool_call in getattr(step_details, "tool_calls", []):
                    from_args = self._extract_sql_from_function_args(tool_call)
                    from_out = self._extract_sql_from_output(tool_call)
                    sql_queries.extend(from_args)
                    sql_queries.extend(from_out)

                    data_preview = self._extract_structured_data_from_output(tool_call)
                    if data_preview and (from_args or from_out):
                        combined = from_args + from_out
                        data_retrieval_query = combined[-1]
                        data_retrieval_query_index = len(sql_queries)
                    data_previews.append(data_preview)
        except Exception:
            pass

        return {
            "queries": list(dict.fromkeys(sql_queries)),  # deduplicate, preserve order
            "data_previews": data_previews,
            "data_retrieval_query": data_retrieval_query,
            "data_retrieval_query_index": data_retrieval_query_index,
        }

    def _extract_sql_from_function_args(self, tool_call) -> list[str]:
        import json as _json, re as _re

        sql_keys = {"sql", "query", "sql_query", "statement", "command", "code"}
        results: list[str] = []
        try:
            args_str = getattr(getattr(tool_call, "function", None), "arguments", None)
            if not args_str:
                return results
            try:
                args = _json.loads(args_str)
                if isinstance(args, dict):
                    for k, v in args.items():
                        if k.lower() in sql_keys and isinstance(v, str) and len(v) > 10:
                            results.append(v.strip())
                        elif isinstance(v, dict):
                            for nk, nv in v.items():
                                if nk.lower() in sql_keys and isinstance(nv, str) and len(nv) > 10:
                                    results.append(nv.strip())
            except _json.JSONDecodeError:
                if any(kw in args_str.upper() for kw in ("SELECT", "INSERT", "UPDATE", "DELETE")):
                    for m in _re.findall(
                        r'"(?:sql|query|statement|code)"\s*:\s*"([^"]+)"',
                        args_str, _re.IGNORECASE
                    ):
                        if len(m.strip()) > 10:
                            results.append(m.strip())
        except Exception:
            pass
        return results

    def _extract_sql_from_output(self, tool_call) -> list[str]:
        import json as _json, re as _re

        sql_keys = {"sql", "query", "sql_query", "statement", "command", "code", "generated_code"}
        results: list[str] = []
        try:
            output_str = str(getattr(tool_call, "output", "") or "")
            if not output_str:
                return results
            try:
                data = _json.loads(output_str)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if k.lower() in sql_keys and isinstance(v, str) and len(v) > 10:
                            results.append(v.strip())
                        elif isinstance(v, dict):
                            for nk, nv in v.items():
                                if nk.lower() in sql_keys and isinstance(nv, str) and len(nv) > 10:
                                    results.append(nv.strip())
            except _json.JSONDecodeError:
                pass

            if any(kw in output_str.upper() for kw in ("SELECT", "INSERT", "UPDATE", "DELETE", "FROM")):
                patterns = [
                    r'"(?:sql|query|statement|code|generated_code)"\s*:\s*"([^"]+)"',
                    r'(SELECT\s+.+?FROM\s+.+?)(?=\s*[;}"\'\n]|$)',
                ]
                for pat in patterns:
                    for m in _re.findall(pat, output_str, _re.IGNORECASE | _re.DOTALL):
                        clean = _re.sub(r"\s+", " ", m.strip().replace("\\n", "\n").replace("\\t", "\t"))
                        if len(clean) > 10:
                            results.append(clean)
        except Exception:
            pass
        return results

    def _extract_structured_data_from_output(self, tool_call) -> list[str]:
        import json as _json

        lines: list[str] = []
        try:
            output_str = str(getattr(tool_call, "output", "") or "")
            if not output_str:
                return lines
            try:
                data = _json.loads(output_str)
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    headers = list(data[0].keys())
                    lines.append("| " + " | ".join(headers) + " |")
                    lines.append("|" + "---|" * len(headers))
                    for row in data[:10]:
                        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
                elif isinstance(data, dict):
                    for key in ("data", "results"):
                        if key in data and isinstance(data[key], list):
                            return self._format_list_data(data[key])
                    lines.append("| Key | Value |")
                    lines.append("|---|---|")
                    for k, v in data.items():
                        lines.append(f"| {k} | {v} |")
            except _json.JSONDecodeError:
                pass
        except Exception:
            pass
        return lines

    @staticmethod
    def _format_list_data(data: list) -> list[str]:
        if not data or not isinstance(data[0], dict):
            return []
        headers = list(data[0].keys())
        lines = [
            "| " + " | ".join(headers) + " |",
            "|" + "---|" * len(headers),
        ]
        for row in data[:10]:
            lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
        return lines

    def _extract_data_from_text_response(self, text: str) -> list[str]:
        import re as _re

        # Prefer a raw markdown table if present
        table = self._extract_markdown_table(text)
        if table:
            return [table]

        # Fall back to numbered-list parsing
        lines = text.split("\n")
        rows = [_re.sub(r"^\d+\.\s+", "", l.strip()) for l in lines if _re.match(r"^\d+\.\s+", l.strip())]
        if not rows:
            return []

        first = rows[0]
        if ":" not in first:
            return [f"Row {i+1}: {r}" for i, r in enumerate(rows)]

        pairs0 = [p.split(":", 1) for p in first.split(", ") if ":" in p]
        headers = [p[0].strip() for p in pairs0]
        result = [
            "| " + " | ".join(headers) + " |",
            "|" + "---|" * len(headers),
            "| " + " | ".join(p[1].strip() for p in pairs0) + " |",
        ]
        for row in rows[1:]:
            vals = [p.split(":", 1)[1].strip() for p in row.split(", ") if ":" in p]
            if len(vals) == len(headers):
                result.append("| " + " | ".join(vals) + " |")
        return result

    @staticmethod
    def _extract_markdown_table(text: str) -> str:
        lines = text.split("\n")
        table: list[str] = []
        in_table = False

        for line in lines:
            stripped = line.strip()
            if "|" in stripped and ("---" in stripped or stripped.count("-") > 3):
                table.append(line)
                in_table = True
            elif "|" in stripped and (in_table or not table):
                table.append(line)
                in_table = True
            elif in_table and stripped == "":
                table.append(line)
            elif in_table and "|" not in stripped and stripped:
                break

        while table and not table[-1].strip():
            table.pop()

        return "\n".join(table) if len(table) >= 2 else ""


# ---------------------------------------------------------------------------
# Module-level singleton — one client per process, shared across requests.
# ---------------------------------------------------------------------------

def get_fabric_client(data_agent_url: str) -> FabricDataAgentClient:
    """Return the process-level FabricDataAgentClient, creating it on first call."""
    global _fabric_client
    if _fabric_client is None:
        _fabric_client = FabricDataAgentClient(data_agent_url)
    return _fabric_client


_fabric_client: FabricDataAgentClient | None = None
