import logging
import os

from telegram import Bot

logger = logging.getLogger(__name__)


async def send_telegram_message(chat_id: str, text: str) -> bool:
    """텔레그램 메시지를 전송합니다."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN이 설정되어 있지 않아 메시지를 보낼 수 없습니다.")
        return False

    try:
        bot = Bot(token=token)
        await bot.send_message(chat_id=chat_id, text=text)
        return True
    except Exception:
        logger.exception("텔레그램 메시지 전송 실패 (chat_id: %s)", chat_id)
        # 알림 전송 실패가 전체 프로세스를 중단시키지 않도록 예외만 기록
        return False
