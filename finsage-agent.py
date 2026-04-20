#!/usr/bin/env python3
"""
Example: Microsoft Agent Framework calling a Fabric Data Agent
using Managed Identity (DefaultAzureCredential) for authentication.

Architecture:
    User ──► Agent Framework Agent (Foundry LLM)
                      │
                      ▼  tool call
              query_fabric_data_agent()
                      │
                      ▼  Bearer token (Managed Identity)
              Fabric Data Agent API

When deployed to Azure (VM, AKS, Container App, App Service, etc.),
DefaultAzureCredential automatically uses the resource's Managed Identity.
Locally it falls back to: env vars → VS Code → Azure CLI → etc.

Required environment variables (see .env.template):
    FOUNDRY_PROJECT_ENDPOINT         Azure AI Foundry project endpoint
    FOUNDRY_MODEL_DEPLOYMENT_NAME    Model deployment name (e.g. gpt-4o)
    DATA_AGENT_URL                   Published Fabric Data Agent URL

Install:
    pip install agent-framework-core==1.0.1 \\
                agent-framework-foundry==1.0.1 \\
                agent-framework-openai==1.0.1
"""

import asyncio
import os
import time
import uuid
import warnings

import requests
from dotenv import load_dotenv
from openai import OpenAI

from azure.identity import DefaultAzureCredential
from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient

# Suppress OpenAI Assistants API deprecation warnings
# (Fabric Data Agents don't support the newer Responses API yet)
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r".*Assistants API is deprecated.*",
)

# override=False so Foundry runtime env vars take precedence over local .env
load_dotenv(override=False)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_AGENT_URL = os.getenv("DATA_AGENT_URL", "")
FOUNDRY_PROJECT_ENDPOINT = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "")
FOUNDRY_MODEL_DEPLOYMENT_NAME = os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4o")

_FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"

# One shared credential instance — DefaultAzureCredential caches tokens internally
# and uses Managed Identity automatically when running inside Azure.
_credential = DefaultAzureCredential()


# ---------------------------------------------------------------------------
# Fabric Data Agent helpers
# ---------------------------------------------------------------------------

def _fabric_headers() -> dict:
    """Build request headers with a fresh Fabric bearer token."""
    token = _credential.get_token(_FABRIC_SCOPE)
    return {
        "Authorization": f"Bearer {token.token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "ActivityId": str(uuid.uuid4()),
    }


def _get_or_create_thread(data_agent_url: str, thread_name: str) -> dict:
    """
    Call the Fabric-specific threads endpoint to get or create a conversation thread.
    This endpoint is not part of the OpenAI spec — it is Fabric-specific.
    """
    base_url = (
        data_agent_url
        .removesuffix("/openai")
        .replace("/aiassistant", "/__private/aiassistant")
    )
    url = f'{base_url}/threads/fabric?tag="{thread_name}"'
    response = requests.get(url, headers=_fabric_headers())
    response.raise_for_status()
    thread = response.json()
    thread["name"] = thread_name
    return thread


# ---------------------------------------------------------------------------
# Agent Framework tool
# ---------------------------------------------------------------------------

def query_fabric_data_agent(question: str) -> str:
    """
    Query the Microsoft Fabric Data Agent with a natural language question and
    return the agent's answer.

    Use this tool whenever the user asks about data, metrics, tables, or reports
    that reside in the Microsoft Fabric Data Agent.

    Args:
        question: The natural language question to send to the Fabric Data Agent.

    Returns:
        The data agent's text response.
    """
    # Build an OpenAI client that routes to the Fabric Data Agent endpoint.
    # The Bearer token is obtained from Managed Identity via DefaultAzureCredential.
    token = _credential.get_token(_FABRIC_SCOPE)
    client = OpenAI(
        api_key="",           # not used — Fabric uses Bearer auth
        base_url=DATA_AGENT_URL,
        default_query={"api-version": "2024-05-01-preview"},
        default_headers={
            "Authorization": f"Bearer {token.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "ActivityId": str(uuid.uuid4()),
        },
    )

    # Fabric ignores the model value — it uses its own internal model
    assistant = client.beta.assistants.create(model="not used")

    # Each invocation uses a new thread so conversations stay isolated
    thread_name = f"mi-agent-{uuid.uuid4()}"
    thread = _get_or_create_thread(DATA_AGENT_URL, thread_name)

    client.beta.threads.messages.create(
        thread_id=thread["id"],
        role="user",
        content=question,
    )

    run = client.beta.threads.runs.create(
        thread_id=thread["id"],
        assistant_id=assistant.id,
    )

    # Poll until the run finishes (max ~120 s)
    deadline = time.time() + 120
    while run.status in ("queued", "in_progress"):
        if time.time() > deadline:
            return "Request to Fabric Data Agent timed out."
        time.sleep(2)
        run = client.beta.threads.runs.retrieve(
            thread_id=thread["id"],
            run_id=run.id,
        )

    # Collect assistant messages
    messages = client.beta.threads.messages.list(
        thread_id=thread["id"],
        order="asc",
    )
    responses: list[str] = []
    for msg in messages.data:
        if msg.role == "assistant":
            try:
                content = msg.content[0]
                if hasattr(content, "text"):
                    responses.append(content.text.value)
                else:
                    responses.append(str(content))
            except (IndexError, AttributeError):
                responses.append(str(msg.content))

    # Best-effort thread cleanup
    try:
        client.beta.threads.delete(thread_id=thread["id"])
    except Exception:
        pass

    return "\n".join(responses) if responses else "No response received from the Fabric Data Agent."


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

async def main() -> None:
    if not DATA_AGENT_URL or DATA_AGENT_URL == "your-data-agent-url-here":
        print("❌  DATA_AGENT_URL is not set. Add it to your .env file or environment.")
        return
    if not FOUNDRY_PROJECT_ENDPOINT:
        print("❌  FOUNDRY_PROJECT_ENDPOINT is not set. Add it to your .env file or environment.")
        return

    print("🔐  Using DefaultAzureCredential (Managed Identity in Azure / fallback chain locally)")
    print(f"🤖  Foundry model : {FOUNDRY_MODEL_DEPLOYMENT_NAME}")
    print(f"📊  Fabric agent  : {DATA_AGENT_URL}")
    print("=" * 60)

    # DefaultAzureCredential is shared — the same instance works for both
    # the Foundry client and the Fabric tool above.
    foundry_client = FoundryChatClient(
        project_endpoint=FOUNDRY_PROJECT_ENDPOINT,
        model=FOUNDRY_MODEL_DEPLOYMENT_NAME,
        credential=_credential,          # sync DefaultAzureCredential per best practices
    )

    async with Agent(
        client=foundry_client,
        name="FabricDataAnalyst",
        instructions=(
            "You are a helpful data analyst assistant. "
            "When the user asks about data, metrics, reports, or tables, "
            "use the query_fabric_data_agent tool to retrieve information from "
            "the Microsoft Fabric Data Agent. "
            "Always base your answers on what the tool returns. "
            "If the tool returns an error, communicate it clearly to the user."
        ),
        tools=[query_fabric_data_agent],
    ) as agent:
        print("\n✅  Agent ready. Type your question or 'quit' to exit.\n")

        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                break

            response = await agent.run(user_input)
            print(f"\nAgent: {response.text}\n")


if __name__ == "__main__":
    asyncio.run(main())
