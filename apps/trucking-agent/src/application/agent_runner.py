from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient

from src.infrastructure.config import settings
from src.infrastructure.identity import credential
from src.prompts.system import SYSTEM_PROMPT
from src.tools.fabric_data_agent_http_tool import query_fabric_data_agent
from src.tools.fabric_data_agent_rpc_tool import get_fabric_data_agent_tools

TOOL_REGISTRY = {
    "fabric_data_agent": lambda user_id: [get_fabric_data_agent_tools(user_id)],
    "fabric_query": lambda user_id: [query_fabric_data_agent],
}

def _get_tools(user_id: str):
    return TOOL_REGISTRY[settings.tool_mode](user_id)

# Created once at module level — reuses the underlying HTTP connection pool
# and token cache across all requests instead of rebuilding it per call.
_foundry_client = FoundryChatClient(
    project_endpoint=settings.foundry_project_endpoint,
    model=settings.foundry_model_deployment_name,
    credential=credential,
)


async def run_query(question: str) -> str:
    """
    Orchestrate a single question through the Trucking agent and return the answer.

    A new Agent context is created per request to keep calls stateless.
    """
    async with Agent(
        client=_foundry_client,
        name="TruckingDataAnalyst",
        instructions=SYSTEM_PROMPT,
        tools=_get_tools("test_user"),
    ) as agent:
        response = await agent.run(question)
        return response.text
