"""텔레그램 Bot API 얇은 래퍼. 라이브러리 없이 HTTP 로만."""
from __future__ import annotations

import html
import logging

import httpx

from .config import cfg

log = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{method}"


def _call(method: str, payload: dict, timeout: float = 30.0) -> dict:
    url = API.format(token=cfg.telegram_token, method=method)
    resp = httpx.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"telegram {method} 실패: {data}")
    return data.get("result", {})


def send_message(chat_id: str, text: str) -> None:
    try:
        _call("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
    except (httpx.HTTPError, RuntimeError) as e:
        # 사용자가 봇을 차단하면 403. 다이제스트 전체가 죽지 않게 삼킨다.
        log.warning("chat %s 전송 실패: %s", chat_id, e)


def get_updates(offset: int | None, timeout: int = 25) -> list[dict]:
    payload = {"timeout": timeout, "allowed_updates": ["message"]}
    if offset is not None:
        payload["offset"] = offset
    try:
        return _call("getUpdates", payload, timeout=timeout + 10)
    except (httpx.HTTPError, RuntimeError) as e:
        log.warning("getUpdates 실패: %s", e)
        return []


def set_webhook(url: str, secret: str) -> dict:
    """웹훅을 걸고 롱폴링을 끈다. 둘은 동시에 못 쓴다.

    secret_token 은 텔레그램이 이후 매 요청의
    X-Telegram-Bot-Api-Secret-Token 헤더에 실어 보낸다. 공개 URL 인 웹훅
    엔드포인트가 진짜 텔레그램에서 온 요청인지 가리는 유일한 수단이다.
    """
    return _call("setWebhook", {
        "url": url,
        "secret_token": secret,
        "allowed_updates": ["message"],
        # 폴링 시절 쌓인 밀린 업데이트가 배포 직후 한꺼번에 쏟아지지 않게.
        "drop_pending_updates": True,
    })


def delete_webhook() -> dict:
    return _call("deleteWebhook", {"drop_pending_updates": False})


def webhook_info() -> dict:
    return _call("getWebhookInfo", {})


def esc(s: str) -> str:
    return html.escape(s or "", quote=False)
