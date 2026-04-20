import time
import uuid

from fastapi import APIRouter, HTTPException

from src.application.agent_runner import run_query
from src.domain.models import QueryRequest, QueryResponse
from src.telemetry.events import log_query_completed, log_query_failed, log_query_received

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/query", response_model=QueryResponse)
async def query_agent(request: QueryRequest) -> QueryResponse:
    """Submit a natural language question to the FinSAGE data agent."""
    session_id = request.session_id or str(uuid.uuid4())
    log_query_received(session_id, request.question)

    start = time.monotonic()
    try:
        answer = await run_query(request.question)
    except Exception as exc:
        log_query_failed(session_id, str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    duration_ms = (time.monotonic() - start) * 1000
    log_query_completed(session_id, duration_ms)

    return QueryResponse(answer=answer, session_id=session_id)
