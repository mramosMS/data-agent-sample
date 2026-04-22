# Trucking Agent

A conversational data agent for the Trucking domain. It accepts natural language questions and answers them by querying a **Microsoft Fabric Data Agent**, using **Azure AI Foundry** (GPT-4o) as the reasoning engine.

The service can be run as an **interactive CLI** for local exploration or as a **FastAPI HTTP service** for integration with API Management or other consumers.

---

## How it works

```
User question
     │
     ▼
Agent (Azure AI Foundry / GPT-4o)
     │  calls tool
     ▼
query_fabric_data_agent(question)
     │  REST → Microsoft Fabric Data Agent
     ▼
Structured response (RUN_STATUS · ANSWER · STEPS · SQL_QUERIES)
     │
     ▼
Formatted answer returned to caller
```

1. **API layer** (`src/api/`) — FastAPI application that exposes `POST /agent/query` and `GET /health`.
2. **Application layer** (`src/application/agent_runner.py`) — Creates a stateless `Agent` per request using `agent-framework`. The agent is given the `query_fabric_data_agent` tool and a domain-specific system prompt.
3. **Tool** (`src/tools/fabric_tool.py`) — Wraps the Fabric Data Agent REST API. Submits the question, polls until completion, extracts the answer, steps, and any SQL queries executed.
4. **Fabric adapter** (`src/infrastructure/fabric_adapter.py`) — Handles authentication against the Fabric API (`https://api.fabric.microsoft.com/.default`) using `DefaultAzureCredential`, manages token refresh, and drives the Assistants-style thread lifecycle (create thread → add message → create run → poll → retrieve results).
5. **Identity** (`src/infrastructure/identity.py`) — Singleton `DefaultAzureCredential`. Uses Managed Identity in Azure; falls back to environment variables, VS Code, or Azure CLI locally.

### Interactive console

`python main.py` starts a REPL loop. After each answer the console prints a run-details block showing status, elapsed time, reasoning steps, and SQL queries executed.

### HTTP API

`python main.py --serve` starts the FastAPI server on `127.0.0.1:8200`. Interactive Swagger UI is available at `http://127.0.0.1:8200/docs`.

In production (Docker / Container Apps) the server listens on `0.0.0.0:8000`.

---

## Configuration

Configuration is loaded from environment variables or a `.env` file via `pydantic-settings`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `FOUNDRY_PROJECT_ENDPOINT` | **Yes** | — | Azure AI Foundry project endpoint URL (e.g. `https://<hub>.services.ai.azure.com/api/projects/<project>`) |
| `FOUNDRY_MODEL_DEPLOYMENT_NAME` | No | `gpt-4o` | Name of the model deployment in Foundry to use as the reasoning engine |
| `DATA_AGENT_URL` | **Yes** | — | Microsoft Fabric Data Agent OpenAI-compatible endpoint URL |

Create a `.env` file in the `apps/trucking-agent/` directory (see [Local setup](#local-setup)):

```dotenv
FOUNDRY_PROJECT_ENDPOINT=https://<hub>.services.ai.azure.com/api/projects/<project>
FOUNDRY_MODEL_DEPLOYMENT_NAME=gpt-4o
DATA_AGENT_URL=https://<workspace>.fabric.microsoft.com/.../<agent-id>/openai
```

---

## Local setup

### Prerequisites

- Python 3.12+
- Azure CLI logged in (`az login`) **or** another credential supported by `DefaultAzureCredential`
- Access to an Azure AI Foundry project with a GPT-4o deployment
- Access to a Microsoft Fabric workspace with a configured Data Agent

### Steps

```powershell
cd apps/trucking-agent

# Create venv, install dependencies, and copy .env template
.\scripts\setup_local.ps1

# Edit .env with your values
# Then run the interactive console
python main.py

# Or start the HTTP API server
python main.py --serve
```

> The setup script creates `.env` from `.env.template` if it does not already exist. Fill in the required values before running.

---

## API reference

### `POST /agent/query`

Submit a natural language question to the Trucking data agent.

**Request body**

```json
{
  "question": "How many loads were delivered last week?",
  "session_id": "optional-tracking-id"
}
```

**Response**

```json
{
  "answer": "A total of 1,284 loads were delivered last week.",
  "session_id": "optional-tracking-id"
}
```

### `GET /health`

Liveness / readiness probe. Returns `{"status": "ok"}`.

---

## Docker

Build and run locally:

```bash
docker build -t trucking-agent .
docker run --env-file .env -p 8000:8000 trucking-agent
```

The container runs as a non-root user and exposes port `8000`.

---

## Deployment (Azure Container Apps)

The `deploy/containerapp.bicep` template provisions a Container App with:

- **System-assigned Managed Identity** — used by `DefaultAzureCredential` to authenticate to Fabric and Foundry without secrets.
- **Internal ingress only** — the app is not publicly accessible; API Management acts as the public gateway.
- Liveness probe on TCP port 8000 and readiness probe on `GET /health`.

Required Bicep parameters:

| Parameter | Description |
|---|---|
| `environmentId` | Resource ID of the Container Apps environment |
| `containerImage` | Full image reference (e.g. `myacr.azurecr.io/trucking-agent:latest`) |
| `foundryProjectEndpoint` | Azure AI Foundry project endpoint |
| `dataAgentUrl` | Fabric Data Agent URL |
| `foundryModelDeploymentName` | Foundry model deployment name (default: `gpt-4o`) |

After deployment, grant the Container App's Managed Identity the necessary roles:

- **Azure AI Developer** (or equivalent) on the Foundry project
- **Fabric Contributor** (or equivalent) on the Fabric workspace / Data Agent

---

## Project structure

```
apps/trucking-agent/
├── main.py                        # Entry point (CLI + HTTP server)
├── pyproject.toml
├── Dockerfile
├── deploy/
│   └── containerapp.bicep         # Azure Container Apps Bicep template
├── scripts/
│   └── setup_local.ps1            # Local dev setup script
└── src/
    ├── api/                        # FastAPI app, routes (agent, health)
    ├── application/                # agent_runner — orchestrates Agent + tool
    ├── domain/                     # Pydantic request/response models
    ├── infrastructure/             # config, identity, fabric_adapter
    ├── prompts/                    # System prompt for the Trucking agent
    ├── telemetry/                  # Structured logging helpers
    └── tools/                      # query_fabric_data_agent tool
```
