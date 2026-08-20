"""텔레그램 Bot API 얇은 래퍼. 라이브러리 없이 HTTP 로만."""
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


def esc(s: str) -> str:
    return html.escape(s or "", quote=False)
