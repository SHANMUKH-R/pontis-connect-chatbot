from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from pontis_chat.agent.service import ChatService, get_chat_service

router = APIRouter(tags=["chat"])

ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


class ChatRequest(BaseModel):
    question: str = ""
    history: list[str] = Field(default_factory=list, max_length=20)


class Source(BaseModel):
    title: str
    url: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    status: str
    retrieved: list[str]
    mode: str
    flags: list[str]


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, service: ChatServiceDep) -> ChatResponse:
    reply = service.answer(body.question, body.history)
    return ChatResponse(
        answer=reply.answer,
        sources=[Source(**source) for source in reply.sources],
        status=reply.status,
        retrieved=reply.retrieved,
        mode=reply.mode,
        flags=reply.flags,
    )
