from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Natural language question to the data agent")
    session_id: str | None = Field(None, description="Optional session identifier for tracking")


class QueryResponse(BaseModel):
    answer: str = Field(..., description="Data agent's response")
    session_id: str | None = Field(None, description="Session identifier echoed from the request")
