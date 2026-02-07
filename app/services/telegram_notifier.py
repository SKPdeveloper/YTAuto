"""
Telegram Notifier

Sends push notifications via Telegram bot.
Works even when phone is locked or browser is closed.

Setup:
1. Create bot via @BotFather in Telegram
2. Get your chat_id via @userinfobot
3. Add to .env:
   TELEGRAM_BOT_TOKEN=your_bot_token
   TELEGRAM_CHAT_ID=your_chat_id
"""

import httpx
from typing import Optional
from loguru import logger

from app.core.config import settings


class TelegramNotifier:
    """Send notifications via Telegram bot."""

    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)

        if self.enabled:
            logger.info("[Telegram] Notifier enabled")
        else:
            logger.warning("[Telegram] Notifier disabled (no token/chat_id)")

    async def send(self, message: str, parse_mode: str = "HTML") -> bool:
        """
        Send message to Telegram.

        Returns True if sent successfully.
        """
        if not self.enabled:
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": parse_mode,
                })

                if response.status_code == 200:
                    logger.debug(f"[Telegram] Message sent")
                    return True
                else:
                    logger.warning(f"[Telegram] Failed: {response.status_code} {response.text}")
                    return False

        except Exception as e:
            logger.error(f"[Telegram] Error: {e}")
            return False

    async def send_approval_required(
        self,
        project_id: str,
        approval_type: str = "primary",
        count: int = 4,
        url: Optional[str] = None
    ) -> bool:
        """Send approval required notification."""
        emoji = "🎨" if approval_type == "primary" else "🎬"
        type_text = "зображення" if approval_type == "primary" else "відео"

        message = f"""
{emoji} <b>ПОТРІБЕН ВИБІР</b>

Готово <b>{count}</b> {type_text} для проєкту.

👉 <a href="{url or 'http://localhost:8000/control'}">Відкрити панель</a>
"""
        return await self.send(message)

    async def send_pipeline_completed(
        self,
        project_id: str,
        video_url: Optional[str] = None
    ) -> bool:
        """Send pipeline completed notification."""
        message = f"""
✅ <b>ВІДЕО ГОТОВЕ</b>

Проєкт <code>{project_id}</code> завершено!

👉 <a href="{video_url or 'http://localhost:8000/control'}">Переглянути</a>
"""
        return await self.send(message)

    async def send_error(
        self,
        project_id: str,
        error: str
    ) -> bool:
        """Send error notification."""
        from html import escape
        message = f"""
❌ <b>ПОМИЛКА</b>

Проєкт: <code>{escape(project_id)}</code>
Помилка: {escape(error[:200])}
"""
        return await self.send(message)


# Singleton
_notifier: Optional[TelegramNotifier] = None


def get_telegram_notifier() -> TelegramNotifier:
    """Get global TelegramNotifier instance."""
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier
