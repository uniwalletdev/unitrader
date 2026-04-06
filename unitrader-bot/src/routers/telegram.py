import asyncio
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.constants import ChatAction

from config import settings
from database import get_db
from models import OnboardingMessage
from src.agents.core.conversation_agent import ConversationAgent
from src.agents.shared_memory import SharedMemory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])
bot = Bot(token=settings.telegram_bot_token)


async def send_typing_loop(chat_id: int, stop_event: asyncio.Event):
    """
    Sends 'typing...' action every 4 seconds until stop_event is set.
    Telegram typing indicator auto-expires after 5 seconds so we refresh it
    just before it expires to keep it alive for long responses.
    """
    while not stop_event.is_set():
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        try:
            await asyncio.wait_for(asyncio.shield(asyncio.sleep(4)), timeout=4)
        except asyncio.TimeoutError:
            pass


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    data = await request.json()

    message = data.get("message") or data.get("edited_message")
    if not message:
        return {"ok": True}

    chat_id = int(message["chat"]["id"])
    user_message = (message.get("text") or "").strip()
    telegram_user_id = str(message["from"]["id"])

    if not user_message:
        return {"ok": True}

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_typing_loop(chat_id, stop_typing))

    try:
        # STEP 2 — Load conversation history (last 10 turns)
        result = await db.execute(
            select(OnboardingMessage)
            .where(OnboardingMessage.user_id == telegram_user_id)
            .order_by(OnboardingMessage.created_at.desc())
            .limit(20)
        )
        rows = result.scalars().all()
        conversation_history = [
            {"role": row.role, "content": row.content} for row in reversed(rows)
        ]
        if len(conversation_history) > 20:
            conversation_history = conversation_history[-20:]

        # STEP 3 — Load shared context for this user
        shared_context = await SharedMemory.load(user_id=telegram_user_id, db=db)

        # STEP 4 — Generate AI response with channel="telegram"
        conversation_agent = ConversationAgent(user_id=telegram_user_id)
        result = await conversation_agent.respond(
            user_message,
            db=db,
            shared_context=shared_context,
            conversation_history=conversation_history,
            channel="telegram",
        )
        ai_response = (result.get("response") or "").strip()
        if not ai_response:
            ai_response = "Response interrupted. Please try again."

    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    # STEP 6 — Send the AI response (chunk if needed)
    MAX_LENGTH = 4096
    chunks = (
        [ai_response[i : i + MAX_LENGTH] for i in range(0, len(ai_response), MAX_LENGTH)]
        if len(ai_response) > MAX_LENGTH
        else [ai_response]
    )
    for chunk in chunks:
        await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")

    # STEP 7 — Save both messages to history
    db.add(OnboardingMessage(user_id=telegram_user_id, role="user", content=user_message))
    db.add(OnboardingMessage(user_id=telegram_user_id, role="assistant", content=ai_response))
    await db.commit()

    return {"ok": True}


@router.on_event("startup")
async def register_telegram_webhook():
    # Prefer API base URL if present; otherwise use production URL if configured.
    base = (settings.api_base_url or "").rstrip("/")
    if not base:
        logger.warning("api_base_url not set; skipping Telegram webhook registration")
        return
    webhook_url = f"{base}/telegram/webhook"
    try:
        await bot.set_webhook(url=webhook_url)
        logger.info("Telegram webhook set → %s", webhook_url)
    except Exception as exc:
        logger.warning("Telegram webhook registration failed: %s", exc)

