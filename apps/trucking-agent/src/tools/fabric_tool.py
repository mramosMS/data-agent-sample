import asyncio
import time
import uuid

from openai import AsyncOpenAI

from src.infrastructure.config import settings
from src.infrastructure.fabric_adapter import build_openai_client, get_or_create_thread

# Rebuild the client this many seconds before the token actually expires.
_TOKEN_REFRESH_BUFFER = 300

_openai_client: AsyncOpenAI | None = None
_client_expires_at: float = 0.0
_assistant_id: str | None = None


def _get_client() -> AsyncOpenAI:
    """Return the cached AsyncOpenAI client, rebuilding it when the token is near expiry."""
    global _openai_client, _client_expires_at
    if _openai_client is None or time.time() >= _client_expires_at - _TOKEN_REFRESH_BUFFER:
        _openai_client, _client_expires_at = build_openai_client(settings.data_agent_url)
    return _openai_client


async def _get_assistant_id(client: AsyncOpenAI) -> str:
    """Return the cached assistant ID, creating one on first call."""
    global _assistant_id
    if _assistant_id is None:
        assistant = await client.beta.assistants.create(model="not used")
        _assistant_id = assistant.id
    return _assistant_id


async def query_fabric_data_agent(question: str) -> str:
    """
    Query the Microsoft Fabric Data Agent with a natural language question.

    Use this tool whenever the user asks about data, metrics, tables, or reports
    that reside in the Microsoft Fabric Data Agent.

    Args:
        question: The natural language question to send to the Fabric Data Agent.

    Returns:
        The data agent's text response.
    """
    client = _get_client()
    assistant_id = await _get_assistant_id(client)

    thread_name = f"trucking-{uuid.uuid4()}"
    thread = await asyncio.to_thread(get_or_create_thread, settings.data_agent_url, thread_name)

    await client.beta.threads.messages.create(
        thread_id=thread["id"],
        role="user",
        content=question,
    )

    run = await client.beta.threads.runs.create(
        thread_id=thread["id"],
        assistant_id=assistant_id,
    )

    deadline = time.time() + 120
    while run.status in ("queued", "in_progress"):
        if time.time() > deadline:
            return "Request to Fabric Data Agent timed out."
        await asyncio.sleep(2)
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
                responses.append(
                    content.text.value if hasattr(content, "text") else str(content)
                )
            except (IndexError, AttributeError):
                responses.append(str(msg.content))

    try:
        await client.beta.threads.delete(thread_id=thread["id"])
    except Exception:
        pass

    return "\n".join(responses) if responses else "No response received from the Fabric Data Agent."
