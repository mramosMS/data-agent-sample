import uuid

import requests
from openai import AsyncOpenAI

from src.infrastructure.identity import credential

_FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"


def _build_headers() -> dict:
    """Build HTTP headers with a fresh Fabric bearer token."""
    token = credential.get_token(_FABRIC_SCOPE)
    return {
        "Authorization": f"Bearer {token.token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "ActivityId": str(uuid.uuid4()),
    }


def _normalize_base_url(data_agent_url: str) -> str:
    """Derive the private base URL used for Fabric-specific thread operations."""
    if "aiskills" in data_agent_url:
        return (
            data_agent_url
            .replace("aiskills", "dataagents")
            .removesuffix("/openai")
            .replace("/aiassistant", "/__private/aiassistant")
        )
    return (
        data_agent_url
        .removesuffix("/openai")
        .replace("/aiassistant", "/__private/aiassistant")
    )


def get_or_create_thread(data_agent_url: str, thread_name: str) -> dict:
    """
    Get or create a Fabric-specific conversation thread.

    This endpoint is Fabric-specific and is not part of the OpenAI spec.
    Returns the thread dict with an added ``name`` key.
    """
    base_url = _normalize_base_url(data_agent_url)
    url = f'{base_url}/threads/fabric?tag="{thread_name}"'

    response = requests.get(url, headers=_build_headers(), timeout=300)
    response.raise_for_status()

    thread = response.json()
    thread["name"] = thread_name
    return thread


def build_openai_client(data_agent_url: str) -> tuple[AsyncOpenAI, float]:
    """Create an AsyncOpenAI client configured to route requests to the Fabric Data Agent.

    Returns:
        A tuple of (client, token_expires_at) where token_expires_at is a Unix
        timestamp so callers can decide when to rebuild the client.
    """
    token = credential.get_token(_FABRIC_SCOPE)
    client = AsyncOpenAI(
        api_key="",  # not used — Fabric authenticates via Bearer token
        base_url=data_agent_url,
        default_query={"api-version": "2024-05-01-preview"},
        default_headers={
            "Authorization": f"Bearer {token.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "ActivityId": str(uuid.uuid4()),
        },
    )
    return client, float(token.expires_on)
