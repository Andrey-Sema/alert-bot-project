import hashlib
import hmac

from alert_bot_project.core_shared.config import config


def hash_peer_id(peer_id: int) -> str:
    """
    Псевдонімізує Telegram user_id/chat_id для безпечного логування.

    Сіль береться з APP_SECRET_KEY; якщо він не заданий (старі деплойменти
    без оновленого .env) — використовується API_HASH, як і раніше робив
    Broadcaster, щоб не ламати сумісність за замовчуванням.
    """
    salt = (config.APP_SECRET_KEY or config.API_HASH).encode()
    return hmac.new(salt, str(peer_id).encode(), hashlib.sha256).hexdigest()[:16]
