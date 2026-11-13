"""POST /api/ask - plain-English questions answered by Claude using the IPO tools."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import schemas
from app.ai.agent import ask
from app.ai.limits import DailyLimiter
from app.config import get_settings
from app.db import get_session

router = APIRouter(prefix="/api", tags=["ask"])

_settings = get_settings()
limiter = DailyLimiter(_settings.ask_per_ip_per_day, _settings.ask_global_per_day)
_client = None


def get_ai_client():
    """Created lazily so the API starts without the anthropic key; overridden in tests."""
    global _client
    settings = get_settings()
    if not settings.anthropic_api_key:
        return None
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


@router.post("/ask", response_model=schemas.AskOut)
def ask_question(body: schemas.AskIn, request: Request, session: Session = Depends(get_session), client=Depends(get_ai_client)):
    settings = get_settings()
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Ask a question.")
    if len(question) > settings.ask_max_question_chars:
        raise HTTPException(status_code=422, detail=f"Keep questions under {settings.ask_max_question_chars} characters.")
    if client is None:
        raise HTTPException(status_code=503, detail="AI questions are turned off on this server (no API key set).")
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown").split(",")[0].strip()
    ok, why = limiter.allow(ip)
    if not ok:
        raise HTTPException(status_code=429, detail=why)
    try:
        return ask(question, session, client, settings.anthropic_model)
    except Exception as e:  # network or API errors: don't leak details to the browser
        raise HTTPException(status_code=502, detail="The AI service didn't respond. Try again in a minute.") from e
