import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.coach.context import build_coach_context
from pengucoach.db.models import Conversation, Message, User, UserPreference
from pengucoach.db.session import get_db
from pengucoach.llm.service import chat

router = APIRouter(prefix="/coach", tags=["coach"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: uuid.UUID | None = None


@router.post("/chat")
async def coach_chat(payload: ChatRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    conversation = await db.get(Conversation, payload.conversation_id) if payload.conversation_id else None
    if conversation and conversation.user_id != user.id: raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND")
    if not conversation:
        conversation = Conversation(user_id=user.id, title=payload.message[:80]); db.add(conversation); await db.flush()
    db.add(Message(conversation_id=conversation.id, role="user", content=payload.message)); await db.flush()
    rows = (await db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at))).all()
    messages = [{"role": x.role, "content": x.content} for x in rows]
    context = await build_coach_context(db, user)
    pref = await db.get(UserPreference, user.id)
    local_only = True if not pref else (pref.local_ai_only or not pref.cloud_health_ai_allowed)
    try: answer = await chat(db, messages, context, user.locale, local_only=local_only)
    except RuntimeError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.add(Message(conversation_id=conversation.id, role="assistant", content=answer["content"], model_id=uuid.UUID(answer["model_id"])))
    await db.commit()
    return {"conversation_id": str(conversation.id), **answer, "data_used": {"health_days": len(context["health_30d"]), "sleep_days": len(context["sleep_30d"]), "hrv_days": len(context["hrv_30d"]), "activities": len(context["recent_activities"])}}
