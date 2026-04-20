from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient

from src.infrastructure.config import settings
from src.infrastructure.identity import credential
from src.prompts.system import SYSTEM_PROMPT
from src.tools.fabric_tool import query_fabric_data_agent


async def run_query(question: str) -> str:
    """
    Orchestrate a single question through the FinSAGE agent and return the answer.

    A new Agent context is created per request to keep calls stateless.
    """
    foundry_client = FoundryChatClient(
        project_endpoint=settings.foundry_project_endpoint,
        model=settings.foundry_model_deployment_name,
        credential=credential,
    )

    async with Agent(
        client=foundry_client,
        name="FabricDataAnalyst",
        instructions=SYSTEM_PROMPT,
        tools=[query_fabric_data_agent],
    ) as agent:
        response = await agent.run(question)
        return response.text
