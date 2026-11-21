from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai.gemini import GeminiAdapter
from app.api.dependencies import current_user
from app.core.config import Settings
from app.db.models import User
from app.db.session import get_db, get_settings
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat import answer_question

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
) -> ChatResponse:
    """Answer a question about one batch or about everything the user can see.

    Read-only. The answer comes from evidence the server selects for the user's own scope.
    """
    request.app.state.chat_limiter.check(user.id)
    return answer_question(db, user, payload, settings, GeminiAdapter(settings))
