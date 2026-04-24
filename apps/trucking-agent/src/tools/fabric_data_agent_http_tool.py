import json
import re
from typing import Any

from src.infrastructure.config import settings
from src.infrastructure.fabric_openai_adapter import get_fabric_client

# Stores the raw Fabric run from the most recent tool call so the console
# (or any other caller) can display steps and SQL without a second API call.
_last_run_data: dict[str, Any] | None = None


def get_last_run_data() -> dict[str, Any] | None:
    """Return the raw run data from the most recent query_fabric_data_agent call."""
    return _last_run_data


def _extract_answer(messages_dump: dict) -> str:
    """Pull the last assistant message text out of a raw messages dump."""
    for msg in messages_dump.get("data", []):
        if msg.get("role") == "assistant":
            for block in msg.get("content", []):
                if isinstance(block, dict):
                    text = block.get("text", {})
                    if isinstance(text, dict):
                        return text.get("value", "")
                    return str(text)
    return "No answer returned by the Fabric Data Agent."


def _format_steps(steps_dump: dict) -> list[str]:
    """Return a human-readable summary line for each run step."""
    lines: list[str] = []
    for i, step in enumerate(steps_dump.get("data", []), start=1):
        step_type = step.get("type", "unknown")
        status = step.get("status", "")
        details = step.get("step_details", {})

        if step_type == "message_creation":
            msg_id = details.get("message_creation", {}).get("message_id", "")
            lines.append(f"  [{i}] message_creation (status={status}) message_id={msg_id}")
        elif step_type == "tool_calls":
            for tc in details.get("tool_calls", []):
                fn_name = tc.get("function", {}).get("name", tc.get("type", "tool"))
                tc_status = tc.get("status", status)
                lines.append(f"  [{i}] tool_call: {fn_name} (status={tc_status})")
        else:
            lines.append(f"  [{i}] {step_type} (status={status})")
    return lines


def _extract_sql_from_steps(steps_dump: dict) -> list[str]:
    """Return a deduplicated list of SQL strings found in run steps."""
    sql_pattern = re.compile(
        r'(SELECT\s.+?FROM\s.+?)(?=[}\'"\n;]|$)',
        re.IGNORECASE | re.DOTALL,
    )
    seen: set[str] = set()
    queries: list[str] = []
    for step in steps_dump.get("data", []):
        details = step.get("step_details", {})
        for tool_call in details.get("tool_calls", []):
            # Check function arguments and output
            for source in (
                tool_call.get("function", {}).get("arguments", ""),
                tool_call.get("output", "") or "",
            ):
                for match in sql_pattern.findall(str(source)):
                    clean = re.sub(r"\s+", " ", match.strip().replace("\\n", "\n"))
                    if clean not in seen:
                        seen.add(clean)
                        queries.append(clean)
    return queries


async def query_fabric_data_agent(question: str) -> str:
    """
    Query the Microsoft Fabric Data Agent with a natural language question.

    Always use this tool whenever the user asks about data, metrics, tables,
    reports, or anything that requires querying the Fabric Data Agent.

    Returns a structured response that always includes:
      - RUN_STATUS: completed / failed / timed_out
      - ANSWER: the agent's plain-text answer
      - STEPS: ordered list of reasoning/tool-call steps the agent took
      - SQL_QUERIES: the SQL statements the agent executed (if any)
      - ERROR: error message if the run failed

    Args:
        question: The natural language question to send to the Fabric Data Agent.
    """
    client = get_fabric_client(settings.data_agent_url)
    raw = await client.get_run_details(question)

    global _last_run_data
    _last_run_data = raw

    if raw.get("run_status") != "completed":
        error = raw.get("error", "Unknown error")
        return f"RUN_STATUS: {raw.get('run_status', 'failed')}\nERROR: {error}"

    steps_dump = raw.get("run_steps", {})
    answer = _extract_answer(raw.get("messages", {}))
    step_lines = _format_steps(steps_dump)
    sql_queries = raw.get("sql_queries", [])  # already extracted by get_run_details

    parts = [
        f"RUN_STATUS: {raw.get('run_status', 'unknown')}",
        f"ANSWER:\n{answer}",
    ]
    if step_lines:
        parts.append("STEPS:\n" + "\n".join(step_lines))
    if sql_queries:
        formatted = "\n\n".join(f"  [{i+1}] {q}" for i, q in enumerate(sql_queries))
        parts.append(f"SQL_QUERIES:\n{formatted}")

    return "\n\n".join(parts)
