from fastapi import FastAPI

from src.api.routes.agent import router as agent_router
from src.api.routes.health import router as health_router

app = FastAPI(
    title="Trucking Agent Service",
    version="0.1.0",
    description=(
        "Internal agent service exposing Trucking data-query capabilities "
        "via the Microsoft Fabric Data Agent. APIM is the public gateway."
    ),
    docs_url="/docs",
    redoc_url=None,
)

app.include_router(health_router)
app.include_router(agent_router)
