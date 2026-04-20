import time
import uuid

from src.infrastructure.config import settings
from src.infrastructure.fabric_adapter import build_openai_client, get_or_create_thread


def query_fabric_data_agent(question: str) -> str:
    """
    Query the Microsoft Fabric Data Agent with a natural language question.

    Use this tool whenever the user asks about data, metrics, tables, or reports
    that reside in the Microsoft Fabric Data Agent.

    Args:
        question: The natural language question to send to the Fabric Data Agent.

    Returns:
        The data agent's text response.
    """
    client = build_openai_client(settings.data_agent_url)
    assistant = client.beta.assistants.create(model="not used")

    thread_name = f"finsage-{uuid.uuid4()}"
    thread = get_or_create_thread(settings.data_agent_url, thread_name)

    client.beta.threads.messages.create(
        thread_id=thread["id"],
        role="user",
        content=question,
    )

    run = client.beta.threads.runs.create(
        thread_id=thread["id"],
        assistant_id=assistant.id,
    )

    deadline = time.time() + 120
    while run.status in ("queued", "in_progress"):
        if time.time() > deadline:
            return "Request to Fabric Data Agent timed out."
        time.sleep(2)
        run = client.beta.threads.runs.retrieve(
            thread_id=thread["id"],
            run_id=run.id,
        )

    messages = client.beta.threads.messages.list(
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
        client.beta.threads.delete(thread_id=thread["id"])
    except Exception:
        pass

    return "\n".join(responses) if responses else "No response received from the Fabric Data Agent."
