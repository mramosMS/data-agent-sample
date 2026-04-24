"""
Fabric Data Agent Tool
Calls the Microsoft Fabric Data Agent endpoint using a Bearer token
via the FabricRpcClient adapter.
"""

import json
from typing import Any, Coroutine

from agent_framework import tool
from src.infrastructure.config import settings
from src.infrastructure.fabric_rpc_adapter import get_fabric_rpc_client

def get_fabric_data_agent_tools(user_id: str):
    """Return the list of Fabric Data Agent tools for a given user.

    The server URL and tool name are read from environment variables so that
    they can be set per-deployment without code changes:

        FABRIC_DATA_AGENT_SERVER_URL  e.g. https://<workspace>.fabric.microsoft.com/...
        FABRIC_DATA_AGENT_TOOL_NAME   the MCP tool name registered in Fabric
    """
    server_url = settings.fabric_data_agent_server_url
    tool_name = settings.fabric_data_agent_tool_name
    #print("Configuring Fabric Data Agent Tool")

    @tool(name="FabricDataAgent", description="Query the Microsoft Fabric Data Agent for trucking data insights.")
    def query_fabric_data_agent(question: str) -> str | Coroutine[Any, Any, str]:
        """Query the Microsoft Fabric Data Agent for read-only information about
        a fleet of trucks, drivers, loads, and routes across regional terminals.
        Use this tool to answer natural-language questions about trips and trucking
        data.
        The Fabric Data Agent has full read-only access to the trucking warehouse and
        will return formatted results.

        Args:
            question: Natural-language question about the user's trucking data.
        """
        if not server_url or not tool_name:
            return json.dumps(
                {
                    "status": "error",
                    "message": (
                        "Fabric Data Agent is not configured. "
                        "Set FABRIC_DATA_AGENT_SERVER_URL and FABRIC_DATA_AGENT_TOOL_NAME "
                        "in your environment."
                    ),
                }
            )

        try:
            client = get_fabric_rpc_client(server_url, tool_name)
            scoped_question = f"[user_id: {user_id}] {question}"
            #return client.ask_raw(scoped_question)
            return client.ask_raw_async(scoped_question)
        except Exception as exc:
            return json.dumps(
                {
                    "status": "error",
                    "message": f"Fabric Data Agent query failed: {exc}",
                }
            )

    return query_fabric_data_agent
